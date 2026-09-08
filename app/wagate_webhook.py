"""
WAGate.app Inbound Webhook Adapter

This module provides the integration layer for receiving inbound WhatsApp
messages and status events forwarded by WAGate.app to our backend.

IMPORTANT: WAGate's external webhook payload format, signature algorithm,
headers, and verification flow are NOT YET DOCUMENTED in their public docs.
This adapter provides the architecture and placeholder interfaces that
will be completed once WAGate provides their official specification.

Architecture:
- Raw request body access for signature verification
- JSON parsing with error handling
- Provider-specific verification interface (to be implemented)
- Idempotency/duplicate event protection
- Seller isolation and channel lookup
- Normalization to internal event format
- Safe delegation to existing conversation/customer/AI pipeline

Internal Normalized Event Format (our format, NOT WAGate's):
{
    "seller_id": "...",
    "external_message_id": "...",
    "from_phone": "...",
    "to_phone": "...",
    "message_type": "text" | "image" | "document" | "audio" | ...,
    "text": "...",
    "timestamp": "...",
    "raw_event": {...}
}
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set
from fastapi import Request, HTTPException, Response

# Use TYPE_CHECKING to avoid circular imports at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.firebase import get_firestore_client
    from app.whatsapp import wagate_service
    from app.models import MessageBase, ChatRequest

logger = logging.getLogger(__name__)

# In-memory store for processed event IDs (per-process, for idempotency)
# In production, consider Redis or Firestore for multi-instance deployments
_PROCESSED_EVENT_IDS: Set[str] = set()
_MAX_PROCESSED_EVENTS = 10000


@dataclass
class NormalizedInboundEvent:
    """Internal normalized event format for inbound WhatsApp messages."""
    seller_id: str
    external_message_id: str
    from_phone: str
    to_phone: str
    message_type: str
    text: str
    timestamp: str
    raw_event: Dict[str, Any]


class WAGateVerificationError(Exception):
    """Raised when WAGate webhook verification fails."""
    pass


class WAGatePayloadError(Exception):
    """Raised when WAGate webhook payload is malformed or missing required fields."""
    pass


class WAGateWebhookVerifier(ABC):
    """
    Abstract base class for WAGate webhook signature verification.
    
    IMPLEMENTATION REQUIRED: Once WAGate provides their official
    webhook signature specification (header name, algorithm, payload format),
    create a concrete subclass implementing verify().
    
    Expected signature methods (common patterns):
    - HMAC-SHA256 with shared secret (like Meta's X-Hub-Signature-256)
    - JWT-based verification
    - Custom header with timestamp + signature
    """
    
    @abstractmethod
    async def verify(
        self,
        request: Request,
        body: bytes,
        credentials: Dict[str, Any]
    ) -> bool:
        """
        Verify the webhook request authenticity.
        
        Args:
            request: FastAPI Request object (for headers, query params)
            body: Raw request body bytes
            credentials: Seller's channel credentials from Firebase
            
        Returns:
            True if verification passes, False otherwise
            
        Raises:
            WAGateVerificationError: If verification fails due to missing config
        """
        pass


class NoOpWAGateVerifier(WAGateWebhookVerifier):
    """
    Placeholder verifier that always passes (for development/testing only).
    
    WARNING: DO NOT USE IN PRODUCTION. Replace with a real verifier
    once WAGate provides their signature specification.
    """
    
    async def verify(
        self,
        request: Request,
        body: bytes,
        credentials: Dict[str, Any]
    ) -> bool:
        logger.warning(
            "WAGate webhook verification SKIPPED (NoOpVerifier). "
            "This is insecure and should only be used in development. "
            "Implement a real WAGateWebhookVerifier once WAGate docs are available."
        )
        return True


# Default verifier - replace with real implementation when WAGate docs available
wagate_verifier: WAGateWebhookVerifier = NoOpWAGateVerifier()


def set_wagate_verifier(verifier: WAGateWebhookVerifier) -> None:
    """Set the WAGate webhook verifier implementation."""
    global wagate_verifier
    wagate_verifier = verifier


class WAGatePayloadParser(ABC):
    """
    Abstract base class for parsing WAGate's external webhook payload
    into our internal NormalizedInboundEvent format.
    
    IMPLEMENTATION REQUIRED: Once WAGate provides their official
    webhook payload documentation, create a concrete subclass implementing
    parse_inbound_messages() and parse_status_updates().
    """
    
    @abstractmethod
    def parse_inbound_messages(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[NormalizedInboundEvent]:
        """
        Parse inbound messages from WAGate's webhook payload.
        
        Args:
            payload: Parsed JSON payload from WAGate
            seller_id: The seller's user ID
            
        Returns:
            List of NormalizedInboundEvent objects
            
        Raises:
            WAGatePayloadError: If payload structure is unexpected
        """
        pass
    
    @abstractmethod
    def parse_status_updates(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[Dict[str, Any]]:
        """
        Parse message status updates (delivered, read, failed) from WAGate's payload.
        
        Args:
            payload: Parsed JSON payload from WAGate
            seller_id: The seller's user ID
            
        Returns:
            List of status update dicts with at least 'external_message_id' and 'status'
        """
        pass


class PlaceholderWAGateParser(WAGatePayloadParser):
    """
    Placeholder parser that raises NotImplementedError.
    
    Replace with a real parser once WAGate provides their payload format.
    """
    
    def parse_inbound_messages(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[NormalizedInboundEvent]:
        raise NotImplementedError(
            "WAGate payload parser not implemented. "
            "Waiting for WAGate's official webhook payload documentation. "
            "Implement a concrete WAGatePayloadParser subclass."
        )
    
    def parse_status_updates(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "WAGate status update parser not implemented. "
            "Waiting for WAGate's official webhook payload documentation."
        )


class MetaFormatWAGateParser(WAGatePayloadParser):
    """
    Concrete parser for WAGate webhook payloads that follow the Meta Cloud API format.
    
    Since WAGate is built on Meta's WhatsApp Cloud API and forwards webhook events,
    this parser handles the standard Meta Cloud API webhook structure:
    {
        "entry": [{
            "id": "<WABA_ID>",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {...},
                    "contacts": [...],
                    "messages": [...],
                    "statuses": [...]
                },
                "field": "messages"
            }]
        }]
    }
    
    This is the same format used by the existing Meta webhook handler in routes.py.
    """
    
    def parse_inbound_messages(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[NormalizedInboundEvent]:
        """
        Parse inbound messages from Meta Cloud API webhook payload format.
        
        Extracts messages from the nested entry/changes/value structure and
        normalizes them to our internal NormalizedInboundEvent format.
        """
        events: List[NormalizedInboundEvent] = []
        
        entry_list = payload.get("entry", [])
        if not entry_list:
            logger.debug(f"No 'entry' in WAGate payload for seller {seller_id}")
            return events
        
        for entry in entry_list:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                
                # Process messages array
                messages = value.get("messages", [])
                for msg in messages:
                    try:
                        event = self._normalize_message(msg, seller_id, value)
                        if event:
                            events.append(event)
                    except Exception as e:
                        logger.error(f"Failed to normalize message for seller {seller_id}: {e}")
                        continue
                
                # Process statuses array (for delivery/read receipts)
                statuses = value.get("statuses", [])
                for status in statuses:
                    # Status updates are handled separately via parse_status_updates
                    pass
        
        return events
    
    def _normalize_message(
        self,
        message: Dict[str, Any],
        seller_id: str,
        value_context: Dict[str, Any]
    ) -> Optional[NormalizedInboundEvent]:
        """
        Normalize a single Meta Cloud API message to our internal format.
        
        Args:
            message: Individual message object from the messages array
            seller_id: The seller's user ID
            value_context: The parent 'value' object containing metadata, contacts, etc.
            
        Returns:
            NormalizedInboundEvent or None if message cannot be processed
        """
        # Extract required fields
        external_message_id = message.get("id", "")
        from_phone = message.get("from", "")
        message_type = message.get("type", "text")
        timestamp = message.get("timestamp", str(int(__import__("time").time())))
        
        if not external_message_id or not from_phone:
            logger.warning(f"Message missing required fields (id/from) for seller {seller_id}: {message}")
            return None
        
        # Extract text content based on message type
        text = self._extract_text_content(message, message_type)
        
        if not text:
            logger.debug(f"Empty text content for message {external_message_id}, type={message_type}")
            # Still create event for non-text messages (images, etc.)
            text = f"[{message_type.title()} received]"
        
        # Determine to_phone from metadata (business phone number)
        to_phone = ""
        metadata = value_context.get("metadata", {})
        if metadata:
            to_phone = metadata.get("display_phone_number", "").replace("+", "").replace(" ", "").replace("-", "")
        
        return NormalizedInboundEvent(
            seller_id=seller_id,
            external_message_id=external_message_id,
            from_phone=from_phone,
            to_phone=to_phone,
            message_type=message_type,
            text=text,
            timestamp=timestamp,
            raw_event=message
        )
    
    def _extract_text_content(self, message: Dict[str, Any], message_type: str) -> str:
        """Extract text content from message based on type."""
        if message_type == "text":
            return message.get("text", {}).get("body", "")
        elif message_type == "interactive":
            # Handle interactive messages (button replies, list replies)
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                return interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                return interactive.get("list_reply", {}).get("title", "")
            return "[Interactive message]"
        elif message_type == "image":
            return "[Image received]"
        elif message_type == "document":
            return "[Document received]"
        elif message_type == "audio":
            return "[Audio message]"
        elif message_type == "video":
            return "[Video received]"
        elif message_type == "sticker":
            return "[Sticker received]"
        elif message_type == "location":
            loc = message.get("location", {})
            return f"[Location: {loc.get('latitude', '')}, {loc.get('longitude', '')}]"
        elif message_type == "contacts":
            return "[Contact(s) shared]"
        elif message_type == "reaction":
            react = message.get("reaction", {})
            return f"[Reaction: {react.get('emoji', '')}]"
        else:
            return f"[{message_type.title()} message]"
    
    def parse_status_updates(
        self,
        payload: Dict[str, Any],
        seller_id: str
    ) -> List[Dict[str, Any]]:
        """
        Parse message status updates (sent, delivered, read, failed) from Meta Cloud API format.
        
        Returns list of status dicts with external_message_id and status.
        """
        status_updates: List[Dict[str, Any]] = []
        
        entry_list = payload.get("entry", [])
        for entry in entry_list:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                statuses = value.get("statuses", [])
                
                for status in statuses:
                    status_updates.append({
                        "external_message_id": status.get("id", ""),
                        "status": status.get("status", ""),  # sent, delivered, read, failed
                        "timestamp": status.get("timestamp", ""),
                        "recipient_id": status.get("recipient_id", ""),
                        "raw_event": status
                    })
        
        return status_updates


# Default parser - Meta Cloud API format (WAGate is built on Meta's Cloud API)
wagate_parser: WAGatePayloadParser = MetaFormatWAGateParser()


def set_wagate_parser(parser: WAGatePayloadParser) -> None:
    """Set the WAGate payload parser implementation."""
    global wagate_parser
    wagate_parser = parser


def _get_event_id(payload: Dict[str, Any], seller_id: str) -> str:
    """
    Extract or compute a unique event ID for idempotency.
    
    Override this function when WAGate's payload structure is known.
    For now, creates a hash of the entire payload + seller_id.
    """
    content = json.dumps(payload, sort_keys=True) + seller_id
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _check_idempotency(event_id: str) -> bool:
    """
    Check if event has already been processed.
    
    Returns:
        True if event is new (not processed), False if duplicate
    """
    global _PROCESSED_EVENT_IDS
    
    if event_id in _PROCESSED_EVENT_IDS:
        logger.info(f"Duplicate WAGate event ignored: {event_id}")
        return False
    
    # Add to processed set
    _PROCESSED_EVENT_IDS.add(event_id)
    
    # Prevent unbounded memory growth
    if len(_PROCESSED_EVENT_IDS) > _MAX_PROCESSED_EVENTS:
        # Remove oldest entries (simple FIFO - in production use Redis with TTL)
        to_remove = len(_PROCESSED_EVENT_IDS) - _MAX_PROCESSED_EVENTS + 1000
        for eid in list(_PROCESSED_EVENT_IDS)[:to_remove]:
            _PROCESSED_EVENT_IDS.discard(eid)
    
    return True


async def _get_seller_channel(seller_id: str) -> Optional[Dict[str, Any]]:
    """Get seller's WhatsApp channel from Firebase."""
    from app.firebase import get_firestore_client
    db = get_firestore_client()
    channel = db.collection("users").document(seller_id).collection("channels").document("whatsapp").get()
    if channel.exists:
        data = channel.to_dict()
        data["id"] = channel.id
        return data
    return None


def _is_wagate_channel(channel: Dict[str, Any]) -> bool:
    """Check if channel is configured for WAGate provider."""
    metadata = channel.get("metadata") or {}
    return metadata.get("provider") == "wagate"


async def handle_wagate_webhook(
    seller_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Main entry point for WAGate webhook processing.
    
    This function:
    1. Reads raw request body
    2. Looks up seller's WAGate channel
    3. Verifies request signature (via verifier interface)
    4. Parses JSON payload
    5. Extracts event ID for idempotency
    6. Normalizes inbound messages via parser interface
    7. Processes each message through existing pipeline
    8. Returns appropriate HTTP response
    
    Args:
        seller_id: The seller's user ID from URL path
        request: FastAPI Request object
        
    Returns:
        Response dict with status
    """
    start_time = time.time()
    
    # 1. Read raw body for signature verification
    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        raise HTTPException(status_code=400, detail="Unable to read request body")
    
    if not body:
        logger.warning(f"Empty WAGate webhook body for seller: {seller_id}")
        raise HTTPException(status_code=400, detail="Empty request body")
    
    # DEBUG: Log incoming request details (sanitized)
    logger.info(f"=== WAGATE WEBHOOK RECEIVED ===")
    logger.info(f"  seller_id from URL: {seller_id}")
    logger.info(f"  request method: {request.method}")
    logger.info(f"  request headers: {dict(request.headers)}")
    logger.info(f"  raw body length: {len(body)} bytes")
    
    # 2. Look up seller's channel
    channel = await _get_seller_channel(seller_id)
    if not channel:
        logger.warning(f"WAGate webhook for unknown seller: {seller_id}")
        # Return 200 to avoid WAGate retries for unknown sellers
        return {"status": "ok", "message": "Seller not found"}
    
    logger.info(f"  channel found: {channel.get('id')}, provider: {channel.get('metadata', {}).get('provider')}")
    
    if not channel.get("credentials"):
        logger.warning(f"WAGate webhook for seller without credentials: {seller_id}")
        return {"status": "ok", "message": "Channel not configured"}
    
    if not _is_wagate_channel(channel):
        logger.info(f"WAGate webhook received but seller uses Meta provider: {seller_id}")
        return {"status": "ok", "message": "Not a WAGate channel"}
    
    # 3. Verify webhook signature
    try:
        verified = await wagate_verifier.verify(request, body, channel["credentials"])
        if not verified:
            logger.warning(f"WAGate webhook verification failed for seller: {seller_id}")
            raise HTTPException(status_code=403, detail="Invalid signature")
        logger.info(f"  signature verification: PASSED")
    except WAGateVerificationError as e:
        logger.error(f"WAGate verification error for seller {seller_id}: {e}")
        raise HTTPException(status_code=403, detail="Verification failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected verification error for seller {seller_id}: {e}")
        raise HTTPException(status_code=500, detail="Verification error")
    
    # 4. Parse JSON payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in WAGate webhook for seller {seller_id}: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Failed to decode WAGate webhook body: {e}")
        raise HTTPException(status_code=400, detail="Invalid request body")
    
    # DEBUG: Log parsed payload structure (sanitized)
    logger.info(f"  parsed payload keys: {list(payload.keys())}")
    if "entry" in payload:
        logger.info(f"  entry count: {len(payload['entry'])}")
        for i, entry in enumerate(payload["entry"]):
            logger.info(f"    entry[{i}] keys: {list(entry.keys())}")
            if "changes" in entry:
                logger.info(f"      changes count: {len(entry['changes'])}")
                for j, change in enumerate(entry["changes"]):
                    logger.info(f"        change[{j}] keys: {list(change.keys())}")
                    if "value" in change:
                        value = change["value"]
                        logger.info(f"          value keys: {list(value.keys())}")
                        if "messages" in value:
                            logger.info(f"          messages count: {len(value['messages'])}")
                            for k, msg in enumerate(value["messages"]):
                                logger.info(f"            msg[{k}]: id={msg.get('id')}, from={msg.get('from')}, type={msg.get('type')}")
                        if "statuses" in value:
                            logger.info(f"          statuses count: {len(value['statuses'])}")
    
    # 5. Idempotency check
    event_id = _get_event_id(payload, seller_id)
    if not _check_idempotency(event_id):
        logger.info(f"  duplicate event ignored: {event_id}")
        return {"status": "ok", "message": "Duplicate event ignored"}
    
    logger.info(f"Processing WAGate webhook for seller {seller_id}, event_id={event_id}")
    
    # 6. Parse and normalize inbound messages
    try:
        normalized_events = wagate_parser.parse_inbound_messages(payload, seller_id)
        logger.info(f"  parser returned {len(normalized_events)} normalized events")
        for idx, event in enumerate(normalized_events):
            logger.info(f"    event[{idx}]: id={event.external_message_id}, from={event.from_phone}, type={event.message_type}, text_len={len(event.text)}")
    except NotImplementedError as e:
        logger.error(f"WAGate parser not implemented: {e}")
        # Return 200 to prevent WAGate retries, but log clearly
        return {
            "status": "error",
            "message": "WAGate inbound parser not implemented. Awaiting WAGate webhook payload documentation."
        }
    except WAGatePayloadError as e:
        logger.error(f"WAGate payload parse error for seller {seller_id}: {e}")
        return {"status": "error", "message": f"Payload parse error: {e}"}
    except Exception as e:
        logger.error(f"Unexpected WAGate payload parse error for seller {seller_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": "Internal parse error"}
    
    # 7. Process each normalized inbound message
    processed_count = 0
    for event in normalized_events:
        try:
            logger.info(f"  processing event: {event.external_message_id}")
            await _process_normalized_event(event, channel)
            processed_count += 1
            logger.info(f"  event {event.external_message_id} processed successfully")
        except Exception as e:
            logger.error(f"Failed to process normalized event {event.external_message_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue processing other events
    
    # 8. Parse and handle status updates (optional, non-blocking)
    try:
        status_updates = wagate_parser.parse_status_updates(payload, seller_id)
        logger.info(f"  status updates parsed: {len(status_updates)}")
        for status in status_updates:
            logger.debug(f"  status: {status}")
    except NotImplementedError:
        logger.debug("  status updates parser not implemented (expected)")
        pass  # Expected until parser is implemented
    except Exception as e:
        logger.warning(f"Failed to parse WAGate status updates: {e}")
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(f"=== WAGATE WEBHOOK COMPLETE: seller={seller_id}, processed={processed_count}, time={elapsed_ms}ms ===")
    
    return {"status": "ok", "processed": processed_count}


async def _process_normalized_event(
    event: NormalizedInboundEvent,
    channel: Dict[str, Any]
) -> None:
    """
    Process a normalized inbound event through the existing pipeline.
    
    This reuses the existing conversation/customer/AI logic from routes.py
    """
    from datetime import datetime
    import zoneinfo
    import time as time_module
    from app.firebase import get_firestore_client
    from app.routes import (
        _find_or_create_customer_by_phone,
        _find_or_create_conversation,
        _send_whatsapp_reply,
        get_user_ai_settings,
        get_user_customer_settings,
        get_user_knowledge_settings,
        get_user_products,
        get_user_business_info,
        _get_seller_general,
    )
    from app.models import MessageBase, ChatRequest
    from app.agent import agent
    
    seller_id = event.seller_id
    phone = event.from_phone
    message_id = event.external_message_id
    message_type = event.message_type
    text = event.text
    timestamp = event.timestamp
    
    if not text:
        logger.debug(f"Skipping empty message {message_id} for seller {seller_id}")
        return
    
    db = get_firestore_client()
    
    # Find or create customer by phone number
    customer = _find_or_create_customer_by_phone(db, seller_id, phone)
    
    # Find or create conversation for this customer
    conversation = _find_or_create_conversation(
        db, seller_id, customer, "WhatsApp", phone
    )
    
    conv_id = conversation["id"]
    
    # Add message to conversation
    now = time_module.time()
    try:
        general = _get_seller_general(db, seller_id)
        tz = zoneinfo.ZoneInfo(general.get("timezone", "Africa/Accra"))
        time_str = datetime.now(tz).strftime("%I:%M %p")
    except Exception:
        time_str = datetime.now().strftime("%I:%M %p")
    
    new_message = {
        "id": int(now * 1000),
        "sender": "customer",
        "content": text,
        "time": time_str,
        "external_id": message_id,
    }
    
    conv_ref = db.collection("users").document(seller_id).collection("conversations").document(conv_id)
    conv_doc = conv_ref.get()
    conv_data = conv_doc.to_dict() if conv_doc.exists else {}
    
    messages = conv_data.get("messages", [])
    messages.append(new_message)
    
    conv_ref.update({
        "messages": messages,
        "lastMessage": text,
        "time": time_str,
        "updatedAt": now,
        "unread": conv_data.get("unread", 0) + 1,
    })
    
    # Update customer last interaction
    customer_ref = db.collection("users").document(seller_id).collection("customers").document(customer["id"])
    customer_ref.update({
        "lastInteraction": f"WhatsApp: {text[:50]}...",
        "updatedAt": now,
    })
    
    # Get AI settings
    ai_settings = get_user_ai_settings(db, seller_id)
    customer_settings = get_user_customer_settings(db, seller_id)
    knowledge_settings = get_user_knowledge_settings(db, seller_id)
    
    # Merge customer settings into ai_settings
    if not customer_settings.get("showProductRecommendations", True):
        ai_settings["productRecommendations"] = False
    ai_settings["showAvailability"] = customer_settings.get("showAvailability", True)
    
    # Check if AI should respond
    if conv_data.get("mode") == "ai" and ai_settings.get("enabled") and ai_settings.get("autoReply"):
        # Generate AI response
        products = get_user_products(db, seller_id)
        business_info = get_user_business_info(db, seller_id)
        
        # Build conversation history for AI
        history = []
        for msg in messages[-6:]:
            history.append(MessageBase(
                id=msg.get("id"),
                sender=msg.get("sender", "customer"),
                content=msg.get("content", ""),
                time=msg.get("time", ""),
            ))
        
        chat_request = ChatRequest(
            message=text,
            conversationId=conv_id,
            conversationHistory=history,
        )
        
        try:
            ai_response = await agent.generate_response(chat_request, products, business_info, ai_settings, knowledge_settings)
            
            # Add AI response to conversation
            ai_message = {
                "id": int((time_module.time()) * 1000),
                "sender": "ai",
                "content": ai_response.response,
                "time": time_str,
            }
            
            messages.append(ai_message)
            conv_ref.update({
                "messages": messages,
                "lastMessage": ai_response.response,
                "time": time_str,
                "updatedAt": time_module.time(),
            })
            
            # Send AI response back via WAGate
            await _send_whatsapp_reply(seller_id, phone, ai_response.response, channel)
            
        except Exception as e:
            logger.error(f"AI response generation failed for seller {seller_id}: {e}")
            # Send fallback message
            fallback = "I'm having trouble processing your request. Please try again later."
            await _send_whatsapp_reply(seller_id, phone, fallback, channel)


async def handle_wagate_webhook_verification(
    seller_id: str,
    request: Request
) -> Response:
    """
    Optional GET verification endpoint for WAGate webhook handshake.
    
    IMPLEMENTATION REQUIRED: Once WAGate documents their webhook
    verification flow (challenge/response, query params, etc.),
    implement the actual verification logic here.
    
    Current behavior: Returns 404 with clear message that verification
    endpoint is not yet implemented.
    """
    logger.info(f"WAGate webhook verification requested for seller: {seller_id}")
    
    # Check if seller exists and has WAGate channel
    channel = await _get_seller_channel(seller_id)
    if not channel or not _is_wagate_channel(channel):
        raise HTTPException(status_code=404, detail="WAGate channel not configured for this seller")
    
    # TODO: Implement actual verification when WAGate docs available
    # Expected pattern (like Meta):
    # - mode = request.query_params.get("hub.mode") or similar
    # - token = request.query_params.get("hub.verify_token") or similar
    # - challenge = request.query_params.get("hub.challenge") or similar
    # - verify token against stored verify_token in credentials
    # - return challenge as plain text
    
    raise HTTPException(
        status_code=501,
        detail="WAGate webhook verification not yet implemented. "
               "Awaiting WAGate's official webhook verification documentation."
    )


# ============================================================
# TEST HELPERS
# ============================================================

def create_test_normalized_event(
    seller_id: str = "test_seller",
    external_message_id: str = "wamid.test123",
    from_phone: str = "15551234567",
    to_phone: str = "15559876543",
    message_type: str = "text",
    text: str = "Hello, test message",
    timestamp: str = "1700000000",
    raw_event: Optional[Dict[str, Any]] = None
) -> NormalizedInboundEvent:
    """Create a test NormalizedInboundEvent for unit testing."""
    return NormalizedInboundEvent(
        seller_id=seller_id,
        external_message_id=external_message_id,
        from_phone=from_phone,
        to_phone=to_phone,
        message_type=message_type,
        text=text,
        timestamp=timestamp,
        raw_event=raw_event or {}
    )


def reset_idempotency_store() -> None:
    """Reset the in-memory idempotency store (for testing)."""
    global _PROCESSED_EVENT_IDS
    _PROCESSED_EVENT_IDS.clear()