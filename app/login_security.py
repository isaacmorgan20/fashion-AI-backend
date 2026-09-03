"""
Login device recognition and security event logging for ThreadOS.

Devices are recognized by a client-generated device ID (stored in localStorage).
Device records and login events are stored in Firestore under users/{uid}/security/.
"""

import hashlib
import time
import logging
from typing import Optional, List, Dict, Any
from app.firebase import get_firestore_client

logger = logging.getLogger(__name__)

DEVICE_COLLECTION = "login_devices"
LOGIN_EVENT_COLLECTION = "login_events"


def hash_device_id(device_id: str) -> str:
    """Hash a device ID for storage."""
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def parse_user_agent(user_agent: str) -> Dict[str, str]:
    """Extract browser and OS info from user agent string."""
    ua = user_agent.lower()
    browser = "Unknown"
    os = "Unknown"
    
    # Browser detection
    if "edg/" in ua:
        browser = "Edge"
    elif "chrome/" in ua or "crios/" in ua:
        browser = "Chrome"
    elif "firefox/" in ua or "fxios/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "msie" in ua or "trident/" in ua:
        browser = "Internet Explorer"
    
    # OS detection
    if "windows nt 10.0" in ua:
        os = "Windows 10"
    elif "windows nt 11.0" in ua or "windows nt 10.0; win64; x64" in ua:
        os = "Windows 11"
    elif "macintosh" in ua or "mac os x" in ua:
        os = "macOS"
    elif "iphone" in ua or "ipad" in ua:
        os = "iOS"
    elif "android" in ua:
        os = "Android"
    elif "linux" in ua:
        os = "Linux"
    elif "cros" in ua:
        os = "Chrome OS"
    
    return {"browser": browser, "os": os}


def get_known_devices(user_id: str) -> List[Dict[str, Any]]:
    """Get all known devices for a user."""
    db = get_firestore_client()
    docs = (
        db.collection("users")
        .document(user_id)
        .collection(DEVICE_COLLECTION)
        .stream()
    )
    devices = []
    for doc in docs:
        device = doc.to_dict()
        devices.append(device)
    return devices


def find_matching_device(user_id: str, device_id: str) -> Optional[Dict[str, Any]]:
    """Find a known device by its device ID hash."""
    db = get_firestore_client()
    device_id_hash = hash_device_id(device_id)
    
    docs = (
        db.collection("users")
        .document(user_id)
        .collection(DEVICE_COLLECTION)
        .where("device_id_hash", "==", device_id_hash)
        .limit(1)
        .stream()
    )
    
    for doc in docs:
        return doc.to_dict()
    
    return None


def create_device_record(
    user_id: str,
    device_id: str,
    user_agent: str,
    ip_address: str,
) -> Dict[str, Any]:
    """Create a new device record for a user."""
    db = get_firestore_client()
    now = time.time()
    device_id_hash = hash_device_id(device_id)
    ua_info = parse_user_agent(user_agent)
    
    device_data = {
        "device_id_hash": device_id_hash,
        "device_name": f"{ua_info['browser']} on {ua_info['os']}",
        "browser": ua_info["browser"],
        "operating_system": ua_info["os"],
        "user_agent": user_agent,
        "first_seen_at": now,
        "last_seen_at": now,
        "last_ip": ip_address,
        "ip_history": [ip_address] if ip_address else [],
        "is_current": True,
    }
    
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(DEVICE_COLLECTION)
        .document(device_id_hash)
    )
    doc_ref.set(device_data)
    
    return device_data


def update_device_record(
    user_id: str,
    device_id: str,
    ip_address: str,
) -> None:
    """Update an existing device record with new activity."""
    db = get_firestore_client()
    now = time.time()
    device_id_hash = hash_device_id(device_id)
    
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(DEVICE_COLLECTION)
        .document(device_id_hash)
    )
    doc = doc_ref.get()
    
    if not doc.exists:
        return
    
    device = doc.to_dict()
    ip_history = device.get("ip_history", [])
    if ip_address and ip_address not in ip_history:
        ip_history.append(ip_address)
        # Keep only last 10 IPs
        ip_history = ip_history[-10:]
    
    doc_ref.update({
        "last_seen_at": now,
        "last_ip": ip_address,
        "ip_history": ip_history,
    })


def create_login_event(
    user_id: str,
    session_id: str,
    device_id: str,
    ip_address: str,
    user_agent: str,
    is_new_device: bool,
    alert_sent: bool = False,
) -> Dict[str, Any]:
    """Create a login security event record."""
    db = get_firestore_client()
    now = time.time()
    ua_info = parse_user_agent(user_agent)
    
    event_data = {
        "id": hashlib.sha256(f"{user_id}:{session_id}:{now}".encode()).hexdigest()[:20],
        "session_id": session_id,
        "device_id_hash": hash_device_id(device_id),
        "device_name": f"{ua_info['browser']} on {ua_info['os']}",
        "browser": ua_info["browser"],
        "operating_system": ua_info["os"],
        "user_agent": user_agent,
        "ip_address": ip_address,
        "timestamp": now,
        "is_new_device": is_new_device,
        "alert_sent": alert_sent,
    }
    
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(LOGIN_EVENT_COLLECTION)
        .document(event_data["id"])
    )
    doc_ref.set(event_data)
    
    return event_data


def get_login_events(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get login events for a user."""
    db = get_firestore_client()
    docs = (
        db.collection("users")
        .document(user_id)
        .collection(LOGIN_EVENT_COLLECTION)
        .order_by("timestamp", direction="DESCENDING")
        .limit(limit)
        .stream()
    )
    
    events = []
    for doc in docs:
        event = doc.to_dict()
        events.append(event)
    
    return events


def check_login_alerts_enabled(user_id: str) -> bool:
    """Check if login alerts are enabled for the user."""
    db = get_firestore_client()
    try:
        settings_doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if settings_doc.exists:
            settings = settings_doc.to_dict()
            security = settings.get("security", {})
            return security.get("loginNotifications", True)
    except Exception:
        pass
    return True  # Default to enabled


def get_user_email(user_id: str) -> Optional[str]:
    """Get the user's email from their profile."""
    db = get_firestore_client()
    doc = db.collection("users").document(user_id).get()
    if doc.exists:
        return doc.to_dict().get("email")
    return None