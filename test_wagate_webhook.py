"""
Tests for WAGate Webhook Adapter

These tests verify the internal adapter architecture without requiring
WAGate's actual webhook payload format (which is not yet documented).

Tests cover:
- NormalizedInboundEvent dataclass creation
- Idempotency/duplicate event protection
- Placeholder verifier behavior
- Placeholder parser behavior (NotImplementedError)
- Internal event normalization helpers
"""

import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.wagate_webhook import (
    NormalizedInboundEvent,
    WAGateWebhookVerifier,
    NoOpWAGateVerifier,
    WAGatePayloadParser,
    PlaceholderWAGateParser,
    WAGateVerificationError,
    WAGatePayloadError,
    wagate_verifier,
    wagate_parser,
    set_wagate_verifier,
    set_wagate_parser,
    _get_event_id,
    _check_idempotency,
    reset_idempotency_store,
    create_test_normalized_event,
)


class TestNormalizedInboundEvent:
    """Test the internal normalized event dataclass."""
    
    def test_create_valid_event(self):
        event = NormalizedInboundEvent(
            seller_id="seller_123",
            external_message_id="wamid.abc123",
            from_phone="15551234567",
            to_phone="15559876543",
            message_type="text",
            text="Hello world",
            timestamp="1700000000",
            raw_event={"test": "data"}
        )
        
        assert event.seller_id == "seller_123"
        assert event.external_message_id == "wamid.abc123"
        assert event.from_phone == "15551234567"
        assert event.to_phone == "15559876543"
        assert event.message_type == "text"
        assert event.text == "Hello world"
        assert event.timestamp == "1700000000"
        assert event.raw_event == {"test": "data"}
    
    def test_create_minimal_event(self):
        event = NormalizedInboundEvent(
            seller_id="seller_123",
            external_message_id="wamid.abc123",
            from_phone="15551234567",
            to_phone="15559876543",
            message_type="text",
            text="Hello world",
            timestamp="1700000000",
            raw_event={}
        )
        
        assert event.raw_event == {}
    
    def test_create_image_event(self):
        event = NormalizedInboundEvent(
            seller_id="seller_123",
            external_message_id="wamid.img456",
            from_phone="15551234567",
            to_phone="15559876543",
            message_type="image",
            text="[Image received]",
            timestamp="1700000000",
            raw_event={"media_id": "media_123"}
        )
        
        assert event.message_type == "image"
        assert event.text == "[Image received]"


class TestIdempotency:
    """Test idempotency/duplicate event protection."""
    
    def setup_method(self):
        reset_idempotency_store()
    
    def test_first_event_allowed(self):
        event_id = "test_event_123"
        result = _check_idempotency(event_id)
        assert result is True
    
    def test_duplicate_event_rejected(self):
        event_id = "test_event_123"
        _check_idempotency(event_id)  # First time
        result = _check_idempotency(event_id)  # Second time
        assert result is False
    
    def test_different_events_allowed(self):
        _check_idempotency("event_1")
        _check_idempotency("event_2")
        result = _check_idempotency("event_3")
        assert result is True
    
    def test_idempotency_store_reset(self):
        _check_idempotency("event_1")
        reset_idempotency_store()
        result = _check_idempotency("event_1")
        assert result is True


class TestEventIdGeneration:
    """Test event ID generation for idempotency."""
    
    def test_consistent_id_for_same_payload(self):
        payload = {"messages": [{"id": "msg1", "text": "hello"}]}
        seller_id = "seller_123"
        
        id1 = _get_event_id(payload, seller_id)
        id2 = _get_event_id(payload, seller_id)
        
        assert id1 == id2
        assert len(id1) == 32  # SHA256 hex truncated to 32 chars
    
    def test_different_id_for_different_payload(self):
        payload1 = {"messages": [{"id": "msg1"}]}
        payload2 = {"messages": [{"id": "msg2"}]}
        seller_id = "seller_123"
        
        id1 = _get_event_id(payload1, seller_id)
        id2 = _get_event_id(payload2, seller_id)
        
        assert id1 != id2
    
    def test_different_id_for_different_seller(self):
        payload = {"messages": [{"id": "msg1"}]}
        
        id1 = _get_event_id(payload, "seller_1")
        id2 = _get_event_id(payload, "seller_2")
        
        assert id1 != id2


class TestNoOpVerifier:
    """Test the placeholder NoOpWAGateVerifier."""
    
    @pytest.mark.asyncio
    async def test_verify_always_passes(self):
        verifier = NoOpWAGateVerifier()
        mock_request = MagicMock()
        body = b'{"test": "payload"}'
        credentials = {"api_key": "ag_live_sk_test"}
        
        result = await verifier.verify(mock_request, body, credentials)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_verify_logs_warning(self, caplog):
        verifier = NoOpWAGateVerifier()
        mock_request = MagicMock()
        body = b'{"test": "payload"}'
        credentials = {"api_key": "ag_live_sk_test"}
        
        with caplog.at_level(logging.WARNING):
            await verifier.verify(mock_request, body, credentials)
        
        assert "verification SKIPPED" in caplog.text
        assert "NoOpVerifier" in caplog.text


class TestPlaceholderParser:
    """Test the placeholder WAGate payload parser."""
    
    def test_parse_inbound_messages_raises_not_implemented(self):
        parser = PlaceholderWAGateParser()
        payload = {"test": "data"}
        seller_id = "seller_123"
        
        with pytest.raises(NotImplementedError) as exc_info:
            parser.parse_inbound_messages(payload, seller_id)
        
        assert "WAGate payload parser not implemented" in str(exc_info.value)
        assert "Waiting for WAGate" in str(exc_info.value)
    
    def test_parse_status_updates_raises_not_implemented(self):
        parser = PlaceholderWAGateParser()
        payload = {"test": "data"}
        seller_id = "seller_123"
        
        with pytest.raises(NotImplementedError) as exc_info:
            parser.parse_status_updates(payload, seller_id)
        
        assert "WAGate status update parser not implemented" in str(exc_info.value)


class TestVerifierInterface:
    """Test the abstract verifier interface."""
    
    def test_cannot_instantiate_abstract_verifier(self):
        with pytest.raises(TypeError):
            WAGateWebhookVerifier()
    
    def test_can_create_concrete_verifier(self):
        class TestVerifier(WAGateWebhookVerifier):
            async def verify(self, request, body, credentials):
                return True
        
        verifier = TestVerifier()
        assert isinstance(verifier, WAGateWebhookVerifier)
    
    def test_cannot_instantiate_abstract_parser(self):
        with pytest.raises(TypeError):
            WAGatePayloadParser()
    
    def test_can_create_concrete_parser(self):
        class TestParser(WAGatePayloadParser):
            def parse_inbound_messages(self, payload, seller_id):
                return []
            def parse_status_updates(self, payload, seller_id):
                return []
        
        parser = TestParser()
        assert isinstance(parser, WAGatePayloadParser)


class TestVerifierParserRegistration:
    """Test verifier and parser registration functions."""
    
    def setup_method(self):
        # Reset to defaults
        set_wagate_verifier(NoOpWAGateVerifier())
        set_wagate_parser(PlaceholderWAGateParser())
    
    def test_set_custom_verifier(self):
        class CustomVerifier(WAGateWebhookVerifier):
            async def verify(self, request, body, credentials):
                return False
        
        custom = CustomVerifier()
        set_wagate_verifier(custom)
        
        from app.wagate_webhook import wagate_verifier as current
        assert current is custom
    
    def test_set_custom_parser(self):
        class CustomParser(WAGatePayloadParser):
            def parse_inbound_messages(self, payload, seller_id):
                return []
            def parse_status_updates(self, payload, seller_id):
                return []
        
        custom = CustomParser()
        set_wagate_parser(custom)
        
        from app.wagate_webhook import wagate_parser as current
        assert current is custom


class TestCreateTestEvent:
    """Test the test helper function."""
    
    def test_create_test_normalized_event(self):
        event = create_test_normalized_event(
            seller_id="test_seller",
            external_message_id="wamid.test123",
            from_phone="15551234567",
            text="Test message"
        )
        
        assert event.seller_id == "test_seller"
        assert event.external_message_id == "wamid.test123"
        assert event.from_phone == "15551234567"
        assert event.text == "Test message"
        assert event.message_type == "text"
        assert event.raw_event == {}
    
    def test_create_test_event_with_custom_raw(self):
        event = create_test_normalized_event(raw_event={"custom": "data"})
        
        assert event.raw_event == {"custom": "data"}


class TestErrorClasses:
    """Test custom exception classes."""
    
    def test_wagate_verification_error(self):
        error = WAGateVerificationError("Signature mismatch")
        assert str(error) == "Signature mismatch"
        assert isinstance(error, Exception)
    
    def test_wagate_payload_error(self):
        error = WAGatePayloadError("Missing required field: from")
        assert str(error) == "Missing required field: from"
        assert isinstance(error, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])