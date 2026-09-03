"""
Server-side session management for ThreadOS.

Sessions are stored in Firestore at users/{uid}/sessions/{session_id}.
Session tokens are hashed with SHA-256 before storage.
Raw tokens are never persisted.
"""

import hashlib
import secrets
import time
import logging
from typing import Optional, List, Dict, Any
from app.firebase import get_firestore_client
from app.config import get_settings

logger = logging.getLogger(__name__)

SESSION_COLLECTION = "sessions"
TOKEN_HASH_ALGO = "sha256"
DEFAULT_TIMEOUT_MINUTES = 30


def generate_session_token() -> str:
    """Generate a cryptographically secure random session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Hash a session token using SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_timeout_seconds(timeout_minutes: int) -> int:
    """Convert timeout minutes to seconds. 0 means no expiration."""
    if timeout_minutes <= 0:
        return 0
    return timeout_minutes * 60


def get_session_timeout_from_settings(settings: dict) -> int:
    """Extract timeout in minutes from security settings."""
    security = settings.get("security", {})
    timeout_str = security.get("sessionTimeout", "30 minutes")
    timeout_map = {
        "15 minutes": 15,
        "30 minutes": 30,
        "1 hour": 60,
        "4 hours": 240,
        "never": 0,
    }
    return timeout_map.get(timeout_str, 30)


def create_session(
    user_id: str,
    token: str,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
    device_info: Optional[str] = None,
    timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
) -> Dict[str, Any]:
    """
    Create a new session in Firestore.
    Returns the session document (without the raw token).
    """
    db = get_firestore_client()
    now = time.time()
    token_hash = hash_session_token(token)

    timeout_seconds = get_timeout_seconds(timeout_minutes)
    expires_at = now + timeout_seconds if timeout_seconds > 0 else 0

    session_id = hashlib.sha256(
        f"{user_id}:{token_hash}:{now}".encode("utf-8")
    ).hexdigest()[:20]

    session_data = {
        "id": session_id,
        "user_id": user_id,
        "session_token_hash": token_hash,
        "created_at": now,
        "last_active_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "user_agent": user_agent or "",
        "ip_address": ip_address or "",
        "device_info": device_info or "",
    }

    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
        .document(session_id)
    )
    doc_ref.set(session_data)

    return session_data


def validate_session(
    user_id: str,
    session_id: str,
    token: str,
) -> Optional[Dict[str, Any]]:
    """
    Validate a session by ID and token.
    Returns the session dict if valid, None otherwise.
    Checks: existence, token match, expiration, revocation.
    """
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
        .document(session_id)
    )
    doc = doc_ref.get()

    if not doc.exists:
        return None

    session = doc.to_dict()
    now = time.time()

    # Check if revoked
    if session.get("revoked_at") is not None:
        return None

    # Check if expired (0 means no expiration)
    expires_at = session.get("expires_at", 0)
    if expires_at > 0 and now > expires_at:
        return None

    # Verify token hash
    token_hash = hash_session_token(token)
    if token_hash != session.get("session_token_hash"):
        return None

    return session


def touch_session(user_id: str, session_id: str, timeout_minutes: int = 30) -> None:
    """Update last_active_at and extend expiration for active session."""
    db = get_firestore_client()
    now = time.time()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
        .document(session_id)
    )
    doc = doc_ref.get()

    if not doc.exists:
        return

    session = doc.to_dict()
    if session.get("revoked_at") is not None:
        return

    update = {"last_active_at": now}

    # Extend expiration if timeout is configured
    timeout_seconds = get_timeout_seconds(timeout_minutes)
    if timeout_seconds > 0:
        update["expires_at"] = now + timeout_seconds

    doc_ref.update(update)


def revoke_session(user_id: str, session_id: str) -> bool:
    """Revoke a specific session. Returns True if revoked."""
    db = get_firestore_client()
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
        .document(session_id)
    )
    doc = doc_ref.get()

    if not doc.exists:
        return False

    session = doc.to_dict()
    if session.get("revoked_at") is not None:
        return True

    doc_ref.update({"revoked_at": time.time()})
    return True


def revoke_all_sessions(user_id: str, except_session_id: Optional[str] = None) -> int:
    """Revoke all sessions for a user. Returns count of revoked sessions."""
    db = get_firestore_client()
    now = time.time()
    sessions_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
    )
    docs = sessions_ref.stream()

    count = 0
    for doc in docs:
        session = doc.to_dict()
        if session.get("revoked_at") is not None:
            continue
        if except_session_id and doc.id == except_session_id:
            continue
        doc.reference.update({"revoked_at": now})
        count += 1

    return count


def list_sessions(user_id: str) -> List[Dict[str, Any]]:
    """List all sessions for a user (excluding revoked)."""
    db = get_firestore_client()
    sessions_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
    )
    docs = sessions_ref.order_by("created_at").stream()

    sessions = []
    for doc in docs:
        session = doc.to_dict()
        if session.get("revoked_at") is not None:
            continue
        # Remove token hash from response
        session_safe = {k: v for k, v in session.items() if k != "session_token_hash"}
        sessions.append(session_safe)

    return sessions


def delete_expired_sessions(user_id: str) -> int:
    """Clean up expired sessions. Returns count deleted."""
    db = get_firestore_client()
    now = time.time()
    sessions_ref = (
        db.collection("users")
        .document(user_id)
        .collection(SESSION_COLLECTION)
    )
    docs = sessions_ref.stream()

    count = 0
    for doc in docs:
        session = doc.to_dict()
        expires_at = session.get("expires_at", 0)
        if expires_at > 0 and now > expires_at:
            doc.reference.delete()
            count += 1

    return count
