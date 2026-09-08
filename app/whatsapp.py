"""
WhatsApp Business API integration for ThreadOS AI.

This module handles:
- WhatsApp Business API authentication
- Webhook verification (Meta's challenge-response)
- Incoming message processing
- Outbound message sending
- Token management

All credentials are stored securely in Firebase, never exposed to the frontend.
"""

import hashlib
import hmac
import time
import httpx
import logging
from typing import Optional, Dict, Any, List
from app.config import get_settings

logger = logging.getLogger(__name__)

# WhatsApp Business API endpoints
WHATSAPP_API_VERSION = "v21.0"
WHATSAPP_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


class WhatsAppService:
    """Service for WhatsApp Business API operations."""
    
    def __init__(self):
        self.settings = get_settings()
    
    def get_access_token(self, credentials: dict) -> Optional[str]:
        """Extract access token from channel credentials."""
        if not credentials:
            return None
        return credentials.get("access_token")
    
    def get_phone_number_id(self, credentials: dict) -> Optional[str]:
        """Extract phone number ID from channel credentials."""
        if not credentials:
            return None
        return credentials.get("phone_number_id")
    
    def get_business_account_id(self, credentials: dict) -> Optional[str]:
        """Extract WhatsApp Business Account ID from channel credentials."""
        if not credentials:
            return None
        return credentials.get("waba_id")
    
    def get_app_secret(self, credentials: dict) -> Optional[str]:
        """Extract app secret from channel credentials."""
        if not credentials:
            return None
        return credentials.get("app_secret")
    
    def get_verify_token(self, credentials: dict) -> Optional[str]:
        """Extract webhook verify token from channel credentials."""
        if not credentials:
            return None
        return credentials.get("verify_token")
    
    async def verify_webhook_token(
        self,
        mode: str,
        token: str,
        challenge: str,
        credentials: dict
    ) -> Optional[str]:
        """
        Verify Meta's webhook verification request.
        
        When you set up a webhook, Meta sends a GET request with:
        - hub.mode: "subscribe"
        - hub.verify_token: Your verify token
        - hub.challenge: A string to echo back
        
        Returns the challenge string if verification succeeds, None otherwise.
        """
        if mode != "subscribe":
            logger.warning(f"Invalid webhook mode: {mode}")
            return None
        
        verify_token = self.get_verify_token(credentials)
        if not verify_token:
            logger.error("No verify token configured for WhatsApp channel")
            return None
        
        if token != verify_token:
            logger.warning(f"Invalid verify token: {token}")
            return None
        
        return challenge
    
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature_header: str,
        credentials: dict
    ) -> bool:
        """
        Verify the X-Hub-Signature-256 header on incoming webhooks.
        
        Meta signs each webhook request with your app secret.
        The signature is: sha256=HMAC(app_secret, payload)
        """
        app_secret = self.get_app_secret(credentials)
        if not app_secret:
            logger.error("No app secret configured for WhatsApp channel")
            return False
        
        if not signature_header:
            logger.warning("No signature header provided")
            return False
        
        # Parse signature header: "sha256=..."
        if not signature_header.startswith("sha256="):
            logger.warning("Invalid signature format")
            return False
        
        expected_signature = signature_header[7:]  # Remove "sha256=" prefix
        
        # Calculate HMAC
        calculated = hmac.new(
            app_secret.encode("utf-8"),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(calculated, expected_signature)
    
    async def send_text_message(
        self,
        credentials: dict,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send a text message via WhatsApp Business API.
        
        Args:
            credentials: Channel credentials with access_token and phone_number_id
            to_phone: Recipient's phone number (with country code, no + prefix)
            message: Text message to send
            
        Returns:
            API response dict with message ID on success
        """
        access_token = self.get_access_token(credentials)
        phone_number_id = self.get_phone_number_id(credentials)
        
        if not access_token:
            raise ValueError("WhatsApp access token not configured")
        if not phone_number_id:
            raise ValueError("WhatsApp phone number ID not configured")
        
        url = f"{WHATSAPP_BASE_URL}/{phone_number_id}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {
                "body": message
            }
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)
                
                # Handle specific error codes
                if error_code == 190:
                    raise ValueError("WhatsApp access token has expired or is invalid. Please reconnect.")
                elif error_code == 131047:
                    raise ValueError("Recipient phone number is not on WhatsApp.")
                elif error_code == 131026:
                    raise ValueError("Message failed to send. Rate limit exceeded or invalid request.")
                else:
                    raise ValueError(f"WhatsApp API error ({error_code}): {error_message}")
            
            return response.json()
    
    async def get_business_profile(
        self,
        credentials: dict
    ) -> Dict[str, Any]:
        """Get WhatsApp Business profile information."""
        access_token = self.get_access_token(credentials)
        phone_number_id = self.get_phone_number_id(credentials)
        
        if not access_token or not phone_number_id:
            return {}
        
        url = f"{WHATSAPP_BASE_URL}/{phone_number_id}"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            return {}
    
    async def refresh_access_token(
        self,
        credentials: dict
    ) -> Optional[Dict[str, Any]]:
        """
        Refresh a long-lived access token.
        
        Long-lived tokens last 60 days. This method exchanges a valid
        long-lived token for a new one, extending it another 60 days.
        """
        access_token = self.get_access_token(credentials)
        if not access_token:
            return None
        
        # First, extend the token
        url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": credentials.get("app_id", ""),
            "client_secret": credentials.get("app_secret", ""),
            "fb_exchange_token": access_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                new_token = data.get("access_token")
                if new_token:
                    return {
                        **credentials,
                        "access_token": new_token,
                        "token_refreshed_at": time.time()
                    }
            return None


# ============================================================
# WAGate.app WhatsApp API Service
# ============================================================

class WAGateService:
    """Service for WAGate.app WhatsApp API operations.
    
    WAGate is a platform built on top of Meta's WhatsApp Cloud API.
    It handles the Meta connection and exposes a simpler REST API.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.wagate_base_url.rstrip("/")
        # Platform-level API key for testing (set via WAGATE_API_KEY env var)
        self.platform_api_key = self.settings.wagate_api_key
    
    async def send_text_message(
        self,
        credentials: dict,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send a text message via WAGate.app API.
        
        Args:
            credentials: Channel credentials with api_key (seller-specific)
            to_phone: Recipient's phone number (digits only, international format, e.g. 15551234567)
            message: Text message to send
            
        Returns:
            API response dict with wamid and status on success
            
        Raises:
            ValueError: If API key not configured or WAGate returns an error
        """
        api_key = credentials.get("api_key") if credentials else None
        # Fall back to platform API key for testing
        if not api_key:
            api_key = self.platform_api_key
        if not api_key:
            raise ValueError("WAGate API key not configured")
        
        url = f"{self.base_url}/api/messages.php"
        
        payload = {
            "to": to_phone,
            "type": "text",
            "body": message
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30)
            
            # Handle WAGate-specific error codes
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", response.text)
                    error_code = error_data.get("code", response.status_code)
                except Exception:
                    error_message = response.text
                    error_code = response.status_code
                
                if response.status_code == 401:
                    raise ValueError("WAGate API key is invalid, missing, or revoked. Please reconnect.")
                elif response.status_code == 403:
                    raise ValueError("WAGate API access not included in your plan. Upgrade to Growth or Scale.")
                elif response.status_code == 409:
                    raise ValueError("No active WhatsApp connection on the WAGate workspace.")
                elif response.status_code == 422:
                    raise ValueError(f"Invalid request: {error_message}")
                elif response.status_code == 502:
                    raise ValueError("Upstream error from WhatsApp Cloud API. Please try again later.")
                else:
                    raise ValueError(f"WAGate API error ({error_code}): {error_message}")
            
            return response.json()


# Singleton instance
whatsapp_service = WhatsAppService()
wagate_service = WAGateService()
