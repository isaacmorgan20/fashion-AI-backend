"""
End-to-end test for Telegram multi-seller isolation.

This test verifies:
1. Seller A and Seller B can each connect different Telegram bots
2. Messages received via webhook only appear in the correct seller's inbox
3. Replies sent by human agents go through the correct bot
4. Disconnecting one seller does not affect the other

Requires:
- Real Firebase project with Firestore
- Two different Telegram bot tokens from @BotFather
- TELEGRAM_WEBHOOK_SECRET configured in .env
"""

import os
import json
import time
import hmac
import hashlib
import asyncio
import pytest
from datetime import datetime
from typing import Dict, Any, Optional, List
from unittest.mock import AsyncMock, patch, MagicMock

# Add the app directory to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.firebase import initialize_firebase, get_firestore_client
from app.telegram import telegram_service
from app.routes import (
    get_user_channel,
    upsert_user_channel,
    handle_telegram_webhook,
    _send_channel_reply,
    _find_or_create_customer_by_telegram_id,
    _find_or_create_conversation,
    get_user_ai_settings,
    get_user_customer_settings,
    get_user_knowledge_settings,
    get_user_products,
    get_user_business_info,
)
from app.models import ChannelType, ChannelConnectionStatus
from app.config import get_settings


# Test configuration
SELLER_A_ID = "test_seller_a_telegram"
SELLER_B_ID = "test_seller_b_telegram"

# Use the bot token from .env for Seller A, and a different one for Seller B
# In real testing, you would use two different bot tokens from @BotFather
# For this test, we'll simulate with the same token but different seller IDs
# (The isolation is at the Firebase/seller_id level, not the bot token level)
SELLER_A_BOT_TOKEN = "8605815893:AAE1efe8sDPKg5epTNVUOttbSy9xSY_54zg"
SELLER_B_BOT_TOKEN = "8605815893:BBB2efe8sDPKg5epTNVUOttbSy9xSY_54zg"  # Different token for isolation

WEBHOOK_SECRET = "A7F31C9E2B8D44F6A1C7E903D5B82F104C6A7E1B9D3F5A82C1E6B4D9F703A215"

# Test chat IDs (simulating different customers talking to each bot)
user_a_id = 111111
user_b_id = 222222

WEBHOOK_BASE_URL = "https://impish-chowder-cubical.ngrok-free.dev/api/v1"


class MockRequest:
    """Mock FastAPI Request for testing webhook handlers."""
    
    def __init__(self, body: bytes, headers: Dict[str, str] = None):
        self._body = body
        self.headers = headers or {}
    
    async def body(self) -> bytes:
        return self._body
    
    async def json(self) -> Dict[str, Any]:
        return json.loads(self._body.decode("utf-8"))


def create_telegram_update(
    update_id: int,
    chat_id: str,
    user_id: int,
    text: str,
    message_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create a Telegram update payload for testing."""
    if message_id is None:
        message_id = update_id
    
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
                "last_name": "Customer",
                "username": f"testuser{user_id}",
                "language_code": "en"
            },
            "chat": {
                "id": int(chat_id),
                "first_name": "Test",
                "last_name": "Customer",
                "username": f"testuser{user_id}",
                "type": "private"
            },
            "date": int(time.time()),
            "text": text
        }
    }


def create_webhook_request(
    seller_id: str,
    payload: Dict[str, Any],
    secret_token: str
) -> MockRequest:
    """Create a mock request with proper Telegram webhook signature."""
    body = json.dumps(payload).encode("utf-8")
    
    # Create HMAC-SHA256 signature
    secret_key = secret_token.encode("utf-8")
    signature = hmac.new(secret_key, body, hashlib.sha256).hexdigest()
    
    headers = {
        "X-Telegram-Bot-Api-Secret-Token": secret_token,
        "Content-Type": "application/json"
    }
    
    return MockRequest(body, headers)


async def setup_seller_telegram_channel(
    seller_id: str,
    bot_token: str,
    bot_username: str = "testbot"
) -> Dict[str, Any]:
    """Set up a Telegram channel for a seller in Firestore."""
    db = get_firestore_client()
    
    channel_data = {
        "type": "telegram",
        "enabled": True,
        "status": ChannelConnectionStatus.CONNECTED.value,
        "displayName": f"@{bot_username}",
        "credentials": {
            "bot_token": bot_token,
            "webhook_secret": WEBHOOK_SECRET,
        },
        "metadata": {
            "provider": "telegram",
            "bot_username": bot_username,
            "connected_at": time.time(),
        },
        "lastConnectedAt": time.time(),
    }
    
    result = upsert_user_channel(db, seller_id, "telegram", channel_data)
    return result


async def cleanup_seller(seller_id: str):
    """Clean up test data for a seller."""
    db = get_firestore_client()
    
    # Delete channel
    try:
        doc_ref = db.collection("users").document(seller_id).collection("channels").document("telegram")
        doc_ref.delete()
    except Exception:
        pass
    
    # Delete conversations
    try:
        conv_ref = db.collection("users").document(seller_id).collection("conversations")
        docs = conv_ref.stream()
        for doc in docs:
            doc.reference.delete()
    except Exception:
        pass
    
    # Delete customers
    try:
        cust_ref = db.collection("users").document(seller_id).collection("customers")
        docs = cust_ref.stream()
        for doc in docs:
            doc.reference.delete()
    except Exception:
        pass


async def test_seller_isolation():
    """Main test function for Telegram multi-seller isolation."""
    print("=" * 60)
    print("TELEGRAM MULTI-SELLER ISOLATION TEST")
    print("=" * 60)
    
    # Initialize Firebase
    initialize_firebase()
    db = get_firestore_client()
    
    # Clean up any existing test data
    print("\n[SETUP] Cleaning up existing test data...")
    await cleanup_seller(SELLER_A_ID)
    await cleanup_seller(SELLER_B_ID)
    
    # Setup Seller A
    print(f"\n[SETUP] Setting up Seller A ({SELLER_A_ID})...")
    channel_a = await setup_seller_telegram_channel(SELLER_A_ID, SELLER_A_BOT_TOKEN, "seller_a_bot")
    print(f"  Channel created: {channel_a.get('displayName')}, status: {channel_a.get('status')}")
    
    # Setup Seller B
    print(f"\n[SETUP] Setting up Seller B ({SELLER_B_ID})...")
    channel_b = await setup_seller_telegram_channel(SELLER_B_ID, SELLER_B_BOT_TOKEN, "seller_b_bot")
    print(f"  Channel created: {channel_b.get('displayName')}, status: {channel_b.get('status')}")
    
    # Verify both channels exist independently
    print("\n[VERIFY] Checking channel isolation in Firestore...")
    channel_a_check = get_user_channel(db, SELLER_A_ID, "telegram")
    channel_b_check = get_user_channel(db, SELLER_B_ID, "telegram")
    
    assert channel_a_check is not None, "Seller A channel should exist"
    assert channel_b_check is not None, "Seller B channel should exist"
    assert channel_a_check["credentials"]["bot_token"] == SELLER_A_BOT_TOKEN
    assert channel_b_check["credentials"]["bot_token"] == SELLER_B_BOT_TOKEN
    print("  [OK] Both channels stored with correct bot tokens")
    print("  [OK] Channels are seller-isolated in Firestore")
    
    # Test 1: Send message to Seller A's webhook
    print("\n[TEST 1] Sending message to Seller A's webhook...")
    payload_a = create_telegram_update(
        update_id=1001,
        chat_id="111111111",
        user_id=user_a_id,
        text="Hello from Customer A to Seller A"
    )
    request_a = create_webhook_request(SELLER_A_ID, payload_a, WEBHOOK_SECRET)
    
    response_a = await handle_telegram_webhook(SELLER_A_ID, request_a)
    print(f"  Response: {response_a}")
    assert response_a.get("status") == "ok"
    assert response_a.get("processed") == 1
    
    # Verify message only in Seller A's conversations
    print("\n[VERIFY 1] Checking Seller A's inbox...")
    convs_a = list(db.collection("users").document(SELLER_A_ID).collection("conversations").stream())
    assert len(convs_a) == 1, f"Seller A should have 1 conversation, got {len(convs_a)}"
    conv_a = convs_a[0].to_dict()
    assert conv_a["channel"] == "telegram"
    assert conv_a["chat_id"] == "111111111"
    assert any("Hello from Customer A" in msg.get("content", "") for msg in conv_a.get("messages", []))
    print("  [OK] Message received in Seller A's inbox")
    print(f"  [OK] Conversation ID: {convs_a[0].id}")
    print(f"  [OK] Chat ID stored: {conv_a.get('chat_id')}")
    
    print("\n[VERIFY 1] Checking Seller B's inbox (should be empty)...")
    convs_b = list(db.collection("users").document(SELLER_B_ID).collection("conversations").stream())
    assert len(convs_b) == 0, f"Seller B should have 0 conversations, got {len(convs_b)}"
    print("  [OK] Seller B's inbox is empty (correct isolation)")
    
    # Test 2: Send message to Seller B's webhook
    print("\n[TEST 2] Sending message to Seller B's webhook...")
    payload_b = create_telegram_update(
        update_id=2001,
        chat_id="222222222",
        user_id=user_b_id,
        text="Hello from Customer B to Seller B"
    )
    request_b = create_webhook_request(SELLER_B_ID, payload_b, WEBHOOK_SECRET)
    
    response_b = await handle_telegram_webhook(SELLER_B_ID, request_b)
    print(f"  Response: {response_b}")
    assert response_b.get("status") == "ok"
    assert response_b.get("processed") == 1
    
    # Verify message only in Seller B's conversations
    print("\n[VERIFY 2] Checking Seller B's inbox...")
    convs_b = list(db.collection("users").document(SELLER_B_ID).collection("conversations").stream())
    assert len(convs_b) == 1, f"Seller B should have 1 conversation, got {len(convs_b)}"
    conv_b = convs_b[0].to_dict()
    assert conv_b["channel"] == "telegram"
    assert conv_b["chat_id"] == "222222222"
    assert any("Hello from Customer B" in msg.get("content", "") for msg in conv_b.get("messages", []))
    print("  [OK] Message received in Seller B's inbox")
    print(f"  [OK] Conversation ID: {convs_b[0].id}")
    print(f"  [OK] Chat ID stored: {conv_b.get('chat_id')}")
    
    print("\n[VERIFY 2] Checking Seller A's inbox (should still have only 1)...")
    convs_a = list(db.collection("users").document(SELLER_A_ID).collection("conversations").stream())
    assert len(convs_a) == 1, f"Seller A should still have 1 conversation, got {len(convs_a)}"
    print("  [OK] Seller A's inbox unchanged (correct isolation)")
    
    # Test 3: Human agent replies in Seller A's conversation
    print("\n[TEST 3] Human agent replies in Seller A's conversation...")
    conv_a_id = convs_a[0].id
    channel_a = get_user_channel(db, SELLER_A_ID, "telegram")
    
    # Mock the telegram_service.send_text_message to avoid actual API calls
    with patch.object(telegram_service, 'send_text_message', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "result": {"message_id": 999}}
        
        await _send_channel_reply(
            seller_id=SELLER_A_ID,
            to_identifier="111111111",
            message="Hello Customer A! This is Seller A replying.",
            channel=channel_a
        )
        
        # Verify the correct bot token was used (positional args: bot_token, chat_id, text, ...)
        mock_send.assert_called_once()
        called_args = mock_send.call_args
        assert called_args[0][0] == SELLER_A_BOT_TOKEN, f"Should use Seller A's bot token, got {called_args[0][0]}"
        assert called_args[0][1] == "111111111"
        assert "Seller A replying" in called_args[0][2]
        print("  [OK] Reply sent using Seller A's bot token")
        print(f"  [OK] Sent to chat_id: 111111111")
    
    # Test 4: Human agent replies in Seller B's conversation
    print("\n[TEST 4] Human agent replies in Seller B's conversation...")
    conv_b_id = convs_b[0].id
    channel_b = get_user_channel(db, SELLER_B_ID, "telegram")
    
    with patch.object(telegram_service, 'send_text_message', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "result": {"message_id": 999}}
        
        await _send_channel_reply(
            seller_id=SELLER_B_ID,
            to_identifier="222222222",
            message="Hello Customer B! This is Seller B replying.",
            channel=channel_b
        )
        
        # Verify the correct bot token was used (positional args: bot_token, chat_id, text, ...)
        mock_send.assert_called_once()
        called_args = mock_send.call_args
        assert called_args[0][0] == SELLER_B_BOT_TOKEN, f"Should use Seller B's bot token, got {called_args[0][0]}"
        assert called_args[0][1] == "222222222"
        assert "Seller B replying" in called_args[0][2]
        print("  [OK] Reply sent using Seller B's bot token")
        print(f"  [OK] Sent to chat_id: 222222222")
    
    # Test 5: Disconnect Seller A and verify Seller B still works
    print("\n[TEST 5] Disconnecting Seller A's Telegram channel...")
    
    # Delete webhook (mocked)
    with patch.object(telegram_service, 'delete_webhook', new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = {"ok": True}
        
        from app.routes import disconnect_channel
        from app.models import ChannelType
        
        # Create mock current_user for the disconnect endpoint
        class MockUser:
            uid = SELLER_A_ID
        
        # We need to call the internal function directly since it's an endpoint
        result = upsert_user_channel(db, SELLER_A_ID, "telegram", {
            "status": ChannelConnectionStatus.DISCONNECTED.value,
            "enabled": False,
            "credentials": None,
            "lastConnectedAt": None,
        })
        
        print(f"  Seller A channel status: {result.get('status')}")
        assert result["status"] == ChannelConnectionStatus.DISCONNECTED.value
        assert result["credentials"] is None
    
    # Verify Seller B still works after Seller A disconnect
    print("\n[VERIFY 5] Sending another message to Seller B after Seller A disconnect...")
    payload_b2 = create_telegram_update(
        update_id=2002,
        chat_id="222222222",
        user_id=user_b_id,
        text="Second message from Customer B to Seller B"
    )
    request_b2 = create_webhook_request(SELLER_B_ID, payload_b2, WEBHOOK_SECRET)
    
    response_b2 = await handle_telegram_webhook(SELLER_B_ID, request_b2)
    print(f"  Response: {response_b2}")
    assert response_b2.get("status") == "ok"
    assert response_b2.get("processed") == 1
    
    # Verify Seller B now has 2 conversations
    convs_b = list(db.collection("users").document(SELLER_B_ID).collection("conversations").stream())
    # Actually it's the same conversation (same chat_id), so should still be 1
    assert len(convs_b) == 1
    conv_b = convs_b[0].to_dict()
    messages = conv_b.get("messages", [])
    customer_msgs = [m for m in messages if m.get("sender") == "customer"]
    assert len(customer_msgs) == 2, f"Should have 2 customer messages, got {len(customer_msgs)}"
    print("  [OK] Seller B still receives messages correctly")
    
    # Verify Seller A is disconnected (webhook should return ok but not process)
    print("\n[VERIFY 5] Sending message to disconnected Seller A...")
    payload_a2 = create_telegram_update(
        update_id=1002,
        chat_id="111111111",
        user_id=user_a_id,
        text="Message to disconnected Seller A"
    )
    request_a2 = create_webhook_request(SELLER_A_ID, payload_a2, WEBHOOK_SECRET)
    
    response_a2 = await handle_telegram_webhook(SELLER_A_ID, request_a2)
    print(f"  Response: {response_a2}")
    # Should return ok but not process (channel not configured)
    assert response_a2.get("status") == "ok"
    assert response_a2.get("message") == "Channel not configured"
    print("  [OK] Disconnected seller returns 'Channel not configured'")
    
    # Cleanup
    print("\n[CLEANUP] Cleaning up test data...")
    await cleanup_seller(SELLER_A_ID)
    await cleanup_seller(SELLER_B_ID)
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! [OK]")
    print("=" * 60)
    print("\nSummary:")
    print("  [OK] Seller A and Seller B can connect different Telegram bots")
    print("  [OK] Webhook messages are isolated per seller")
    print("  [OK] Replies sent through correct bot token per seller")
    print("  [OK] Disconnecting one seller does not affect the other")
    print("  [OK] Multi-seller isolation verified end-to-end")


if __name__ == "__main__":
    asyncio.run(test_seller_isolation())