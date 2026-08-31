import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore
from app.config import get_settings


def _normalize_private_key(private_key: str) -> str:
    """Normalize private key to proper PEM format with actual newlines."""
    if not private_key:
        return private_key
    
    # Strip whitespace
    key = private_key.strip()
    
    # If key already contains actual newlines (multi-line in .env), use as-is
    if "\n" in key and "\\n" not in key:
        return key
    
    # If key contains literal \n escape sequences, replace them
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    
    # Ensure proper PEM format - add newlines if missing
    if "-----BEGIN PRIVATE KEY-----" in key and "-----END PRIVATE KEY-----" in key:
        # Fix missing newlines around headers/footers
        key = key.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
        key = key.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
        # Clean up any double newlines
        key = "\n".join(line for line in key.splitlines() if line.strip() or line == "")
    
    return key


def initialize_firebase() -> None:
    """Initialize Firebase Admin SDK."""
    if firebase_admin._apps:
        return

    settings = get_settings()

    if not settings.firebase_private_key:
        raise ValueError("FIREBASE_PRIVATE_KEY not configured")

    normalized_key = _normalize_private_key(settings.firebase_private_key)

    cred_dict = {
        "type": "service_account",
        "project_id": settings.firebase_project_id,
        "private_key_id": settings.firebase_private_key_id,
        "private_key": normalized_key,
        "client_email": settings.firebase_client_email,
        "client_id": settings.firebase_client_id,
        "auth_uri": settings.firebase_auth_uri,
        "token_uri": settings.firebase_token_uri,
    }

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)


def get_firestore_client():
    """Get Firestore client."""
    initialize_firebase()
    return firestore.client()


def verify_firebase_token(id_token: str) -> dict:
    """Verify Firebase ID token and return decoded token."""
    initialize_firebase()
    return firebase_auth.verify_id_token(id_token, clock_skew_seconds=60)