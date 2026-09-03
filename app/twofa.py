"""
Two-Factor Authentication (TOTP) for ThreadOS.

Stores TOTP secrets in Firestore at users/{uid}/security/2fa.
Generates QR codes for authenticator app setup.
Verifies TOTP codes during login.
"""

import pyotp
import qrcode
import qrcode.image.svg
import io
import base64
import hashlib
import secrets
import time
import logging
from typing import Optional, Dict, Any, List
from app.firebase import get_firestore_client

logger = logging.getLogger(__name__)

TOTP_ISSUER = "ThreadOS"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30  # seconds
BACKUP_CODES_COUNT = 10


def generate_secret() -> str:
    """Generate a new TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    """Generate the TOTP URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def generate_qr_code_base64(uri: str) -> str:
    """Generate a QR code as a base64-encoded PNG image."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_backup_codes(count: int = BACKUP_CODES_COUNT) -> List[str]:
    """Generate one-time backup codes for account recovery."""
    codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()  # 8-char hex code
        formatted = f"{code[:4]}-{code[4:]}"  # Format as XXXX-XXXX
        codes.append(formatted)
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code for secure storage."""
    return hashlib.sha256(code.replace("-", "").encode("utf-8")).hexdigest()


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against the secret."""
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # Allow 1 interval window
    except Exception as e:
        logger.error(f"TOTP verification error: {e}")
        return False


def setup_2fa(user_id: str, email: str) -> Dict[str, Any]:
    """
    Set up 2FA for a user.
    Returns secret, QR code, and backup codes.
    The secret is stored encrypted in Firestore.
    """
    db = get_firestore_client()

    # Generate secret and backup codes
    secret = generate_secret()
    backup_codes = generate_backup_codes()
    uri = get_totp_uri(secret, email)
    qr_code_base64 = generate_qr_code_base64(uri)

    # Hash backup codes for storage
    hashed_backup_codes = [hash_backup_code(code) for code in backup_codes]

    # Store in Firestore (secret is stored, will be confirmed later)
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc_ref.set({
        "secret": secret,
        "enabled": False,  # Will be enabled after verification
        "backupCodes": hashed_backup_codes,
        "createdAt": time.time(),
        "confirmedAt": None,
    })

    return {
        "secret": secret,
        "qrCode": qr_code_base64,
        "backupCodes": backup_codes,  # Return raw codes once (only time they're shown)
        "uri": uri,
    }


def confirm_2fa(user_id: str, code: str) -> bool:
    """
    Confirm 2FA setup by verifying the TOTP code.
    Enables 2FA for the user if code is valid.
    """
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc = doc_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()
    secret = data.get("secret")

    if not verify_totp(secret, code):
        return False

    # Enable 2FA
    doc_ref.update({
        "enabled": True,
        "confirmedAt": time.time(),
    })

    return True


def verify_2fa_code(user_id: str, code: str) -> bool:
    """
    Verify a 2FA code during login.
    Checks both TOTP and backup codes.
    """
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc = doc_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()

    # Check if 2FA is enabled
    if not data.get("enabled", False):
        return False

    # Try TOTP verification first
    secret = data.get("secret")
    if verify_totp(secret, code):
        return True

    # Try backup code verification
    hashed_code = hash_backup_code(code)
    backup_codes = data.get("backupCodes", [])
    if hashed_code in backup_codes:
        # Remove used backup code
        backup_codes.remove(hashed_code)
        doc_ref.update({"backupCodes": backup_codes})
        return True

    return False


def disable_2fa(user_id: str, code: str) -> bool:
    """
    Disable 2FA for a user.
    Requires a valid TOTP code for security.
    """
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc = doc_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()
    secret = data.get("secret")

    if not verify_totp(secret, code):
        return False

    # Disable 2FA
    doc_ref.update({
        "enabled": False,
        "disabledAt": time.time(),
    })

    return True


def get_2fa_status(user_id: str) -> Dict[str, Any]:
    """Get the 2FA status for a user."""
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc = doc_ref.get()

    if not doc.exists:
        return {"enabled": False, "setupComplete": False}

    data = doc.to_dict()
    return {
        "enabled": data.get("enabled", False),
        "setupComplete": data.get("confirmedAt") is not None,
        "createdAt": data.get("createdAt"),
        "confirmedAt": data.get("confirmedAt"),
        "backupCodesCount": len(data.get("backupCodes", [])),
    }


def regenerate_backup_codes(user_id: str, code: str) -> Optional[List[str]]:
    """
    Regenerate backup codes for a user.
    Requires a valid TOTP code for security.
    """
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection("security")
        .document("2fa")
    )
    doc = doc_ref.get()

    if not doc.exists:
        return None

    data = doc.to_dict()
    secret = data.get("secret")

    if not verify_totp(secret, code):
        return None

    # Generate new backup codes
    backup_codes = generate_backup_codes()
    hashed_backup_codes = [hash_backup_code(c) for c in backup_codes]

    doc_ref.update({"backupCodes": hashed_backup_codes})

    return backup_codes
