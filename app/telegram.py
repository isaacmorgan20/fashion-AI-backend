"""
Telegram Bot API integration for ThreadOS AI.

This module handles:
- Telegram Bot API authentication
- Webhook management (set/get/delete)
- Outbound message sending
- Webhook signature verification

All credentials are stored securely in Firebase, never exposed to the frontend.
"""

import hashlib
import hmac
import logging
from typing import Optional, Dict, Any
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for Telegram Bot API operations."""

    def __init__(self):
        self.settings = get_settings()
        self.bot_token = self.settings.telegram_bot_token
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    async def send_text_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = "HTML",
        reply_to_message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send a text message via Telegram Bot API.

        Args:
            chat_id: Recipient's chat ID (Telegram chat ID)
            text: Message text to send
            parse_mode: Parse mode for message formatting (HTML, Markdown)
            reply_to_message_id: Optional message ID to reply to

        Returns:
            API response dict with message ID on success

        Raises:
            ValueError: If bot token not configured or Telegram returns an error
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")

        url = f"{self.base_url}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)

                # Handle specific Telegram error codes
                if error_code == 403:
                    raise ValueError("Bot was blocked by the user or chat not found")
                elif error_code == 400:
                    raise ValueError(f"Invalid request: {error_message}")
                elif error_code == 429:
                    raise ValueError("Rate limit exceeded. Please try again later.")
                else:
                    raise ValueError(f"Telegram API error ({error_code}): {error_message}")

            return response.json()

    async def send_image_message(
        self,
        chat_id: str,
        image_url: str,
        caption: str = "",
        parse_mode: Optional[str] = "HTML"
    ) -> Dict[str, Any]:
        """
        Send an image message via Telegram Bot API.

        Args:
            chat_id: Recipient's chat ID
            image_url: HTTPS URL of the image to send
            caption: Optional caption for the image
            parse_mode: Parse mode for caption formatting

        Returns:
            API response dict with message ID on success

        Raises:
            ValueError: If bot token not configured or Telegram returns an error
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")
        if not image_url:
            raise ValueError("Image URL is required")
        if not image_url.startswith("https://"):
            raise ValueError("Image URL must be HTTPS for Telegram delivery")

        url = f"{self.base_url}/sendPhoto"

        payload = {
            "chat_id": chat_id,
            "photo": image_url,
        }

        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)

                if error_code == 403:
                    raise ValueError("Bot was blocked by the user or chat not found")
                elif error_code == 400:
                    raise ValueError(f"Invalid request: {error_message}")
                elif error_code == 429:
                    raise ValueError("Rate limit exceeded. Please try again later.")
                else:
                    raise ValueError(f"Telegram API error ({error_code}): {error_message}")

            return response.json()

    async def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        allowed_updates: Optional[list] = None,
        drop_pending_updates: bool = True
    ) -> Dict[str, Any]:
        """
        Set the webhook URL for receiving updates.

        Args:
            url: HTTPS URL to receive updates
            secret_token: Secret token for webhook verification (HMAC-SHA256)
            allowed_updates: List of update types to receive
            drop_pending_updates: Drop all pending updates

        Returns:
            API response dict
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")

        url_endpoint = f"{self.base_url}/setWebhook"

        payload = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }

        if secret_token:
            payload["secret_token"] = secret_token

        if allowed_updates:
            payload["allowed_updates"] = allowed_updates

        async with httpx.AsyncClient() as client:
            response = await client.post(url_endpoint, json=payload, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)
                raise ValueError(f"Failed to set webhook ({error_code}): {error_message}")

            return response.json()

    async def delete_webhook(self, drop_pending_updates: bool = True) -> Dict[str, Any]:
        """
        Delete the webhook.

        Args:
            drop_pending_updates: Drop all pending updates

        Returns:
            API response dict
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")

        url = f"{self.base_url}/deleteWebhook"

        payload = {
            "drop_pending_updates": drop_pending_updates,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)
                raise ValueError(f"Failed to delete webhook ({error_code}): {error_message}")

            return response.json()

    async def get_webhook_info(self) -> Dict[str, Any]:
        """
        Get current webhook status.

        Returns:
            API response dict with webhook info
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")

        url = f"{self.base_url}/getWebhookInfo"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)
                raise ValueError(f"Failed to get webhook info ({error_code}): {error_message}")

            return response.json()

    async def get_me(self) -> Dict[str, Any]:
        """
        Get bot information.

        Returns:
            API response dict with bot info
        """
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured")

        url = f"{self.base_url}/getMe"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30)

            if response.status_code != 200:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", response.text)
                error_code = error_data.get("code", response.status_code)
                raise ValueError(f"Failed to get bot info ({error_code}): {error_message}")

            return response.json()

    def verify_webhook_secret(
        self,
        secret_header: str,
        secret_token: str
    ) -> bool:
        """
        Verify the X-Telegram-Bot-Api-Secret-Token header on incoming webhooks.

        When setting a webhook with secret_token, Telegram sends the secret
        directly in the X-Telegram-Bot-Api-Secret-Token header.

        Args:
            secret_header: Value of X-Telegram-Bot-Api-Secret-Token header
            secret_token: Secret token configured for the webhook

        Returns:
            True if secret matches, False otherwise
        """
        if not secret_token:
            logger.error("No secret token configured for Telegram webhook")
            return False

        if not secret_header:
            logger.warning("No X-Telegram-Bot-Api-Secret-Token header provided")
            return False

        return hmac.compare_digest(secret_header, secret_token)

    async def validate_bot_token(self, bot_token: str) -> bool:
        """
        Validate a bot token by calling getMe.

        Args:
            bot_token: Bot token to validate

        Returns:
            True if valid, False otherwise
        """
        url = f"https://api.telegram.org/bot{bot_token}/getMe"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("ok", False)
        except Exception as e:
            logger.warning(f"Bot token validation failed: {e}")
        return False


# Singleton instance
telegram_service = TelegramService()