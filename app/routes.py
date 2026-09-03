from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, Response
from typing import List, Optional
from datetime import datetime
import logging
from app.models import (
    ConversationBase, ConversationCreate, ConversationUpdate,
    MessageBase, MessageCreate, ProductBase, ProductCreate, ProductUpdate,
    ChatRequest, ChatResponse,
    CustomerBase, CustomerCreate, CustomerUpdate, CustomerStatus,
    OrderBase, OrderCreate, OrderUpdate,
    SettingsBase, SettingsUpdate, AnalyticsResponse,
    NotificationEvent, NotificationEventCreate, NotificationEventType,
    ChannelType, ChannelConnectionStatus, ChannelConnection, ChannelConnectionCreate, ChannelConnectionUpdate,
    StorefrontSettings, PublicStorefront,
    TeamMember, TeamMemberCreate, TeamMemberUpdate, TeamMemberRole, TeamMemberStatus, TeamMemberPermissions,
    Session, SessionCreate
)
from app.firebase import get_firestore_client, verify_firebase_token
from app.agent import agent
from app.whatsapp import whatsapp_service
from app.session import (
    generate_session_token, hash_session_token, create_session,
    validate_session, touch_session, revoke_session, revoke_all_sessions,
    list_sessions, delete_expired_sessions, get_session_timeout_from_settings
)
from app.twofa import (
    setup_2fa, confirm_2fa, verify_2fa_code, disable_2fa,
    get_2fa_status, regenerate_backup_codes
)
from app.login_security import (
    find_matching_device, create_device_record, update_device_record,
    create_login_event, get_login_events, check_login_alerts_enabled,
    get_user_email, parse_user_agent, get_known_devices
)
import time
import hashlib

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["conversations"])


async def get_current_user(
    authorization: str = Header(None),
    x_session_token: str = Header(None),
    x_session_id: str = Header(None),
) -> dict:
    """
    Verify Firebase auth token and optionally validate session.
    
    If X-Session-Token and X-Session-ID headers are provided,
    validates the session against Firestore and updates last_active_at.
    
    Returns decoded Firebase token with uid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    id_token = authorization.split(" ")[1]
    try:
        user_data = verify_firebase_token(id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    
    # If session headers are provided, validate the session
    if x_session_token and x_session_id:
        user_id = user_data.get("uid")
        db = get_firestore_client()
        
        # Get session timeout preference
        try:
            settings_doc = db.collection("users").document(user_id).collection("settings").document("config").get()
            settings = settings_doc.to_dict() if settings_doc.exists else {}
            timeout_minutes = get_session_timeout_from_settings(settings)
        except Exception:
            timeout_minutes = 30
        
        session = validate_session(user_id, x_session_id, x_session_token)
        if session is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        # Update last_active_at (throttled - only if >5 min since last update)
        now = time.time()
        last_active = session.get("last_active_at", 0)
        if now - last_active > 300:  # 5 minutes
            touch_session(user_id, x_session_id, timeout_minutes)
    
    return user_data


def get_user_business_info(db, user_id: str) -> dict:
    """Get business info from user's Firestore document."""
    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {}


def get_user_products(db, user_id: str) -> List[ProductBase]:
    """Get products for the current user's business."""
    products_ref = db.collection("users").document(user_id).collection("products")
    docs = products_ref.stream()
    products = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        products.append(ProductBase(**data))
    return products


def get_user_ai_settings(db, user_id: str) -> dict:
    """Get AI settings for seller, seller-isolated, with defaults. Single source of truth is users/{uid}/settings."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            ai = data.get("ai")
            if isinstance(ai, dict) and ai:
                return ai
    except Exception:
        pass
    return {
        "enabled": True,
        "autoReply": True,
        "productRecommendations": True,
        "customerMemory": True,
        "humanHandoff": True,
        "orderAssistance": True,
        "responseStyle": "Professional",
        "confidenceThreshold": "Medium",
    }


def get_user_customer_settings(db, user_id: str) -> dict:
    """Get customer experience settings for seller, seller-isolated, with defaults."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            customer = data.get("customer")
            if isinstance(customer, dict) and customer:
                return customer
    except Exception:
        pass
    return {
        "welcomeMessage": "Hi! Welcome to our store. How can we help you today?",
        "orderConfirmation": "Your order has been received and is being processed.",
        "showProductRecommendations": True,
        "showAvailability": True,
        "allowCustomerChat": True,
        "allowGuestCheckout": True,
        "collectPhone": True,
        "collectEmail": False,
    }


def get_user_knowledge_settings(db, user_id: str) -> dict:
    """Get knowledge settings for seller, seller-isolated, with defaults."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            knowledge = data.get("knowledge")
            if isinstance(knowledge, dict) and knowledge:
                return {**DEFAULT_SETTINGS["knowledge"], **knowledge}
    except Exception:
        pass
    return DEFAULT_SETTINGS["knowledge"].copy()


@router.get("/conversations", response_model=List[ConversationBase])
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    limit: int = Query(50, le=100)
):
    """List conversations for the current user's business."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    conversations_ref = db.collection("users").document(user_id).collection("conversations")
    query = conversations_ref.order_by("updatedAt", direction="DESCENDING").limit(limit)
    
    if status:
        query = query.where("conversationStatus", "==", status)
    if mode:
        query = query.where("mode", "==", mode)
    
    docs = query.stream()
    conversations = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        conversations.append(ConversationBase(**data))
    
    return conversations


@router.get("/conversations/{conversation_id}", response_model=ConversationBase)
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a single conversation with all messages."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    doc_ref = db.collection("users").document(user_id).collection("conversations").document(conversation_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    data = doc.to_dict()
    data["id"] = doc.id
    return ConversationBase(**data)


@router.post("/conversations", response_model=ConversationBase)
async def create_conversation(
    conversation: ConversationCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new conversation. Adds welcome message from customer settings if configured."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageConversations"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    # Check if customer chat is allowed
    customer_settings = get_user_customer_settings(db, user_id)
    if not customer_settings.get("allowCustomerChat", True):
        raise HTTPException(status_code=403, detail="Customer chat is currently disabled for this business")
    
    now = time.time()
    data = conversation.model_dump()
    
    # Build initial messages with welcome message if configured
    messages = []
    welcome_msg = customer_settings.get("welcomeMessage", "").strip()
    if welcome_msg:
        try:
            import zoneinfo
            general = _get_seller_general(db, user_id)
            tz = zoneinfo.ZoneInfo(general.get("timezone", "Africa/Accra"))
            time_str = datetime.now(tz).strftime("%I:%M %p")
        except Exception:
            time_str = datetime.now().strftime("%I:%M %p")
        welcome_message = MessageBase(
            id=int(now * 1000),
            sender="ai",
            content=welcome_msg,
            time=time_str,
        )
        messages.append(welcome_message.model_dump())
    
    data.update({
        "mode": "ai",
        "conversationStatus": "open",
        "lastMessage": welcome_msg if messages else "",
        "time": "now",
        "unread": 0,
        "orders": [],
        "productsDiscussed": [],
        "messages": messages,
        "createdAt": now,
        "updatedAt": now,
    })
    
    doc_ref = db.collection("users").document(user_id).collection("conversations").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    
    return ConversationBase(**data)


@router.patch("/conversations/{conversation_id}", response_model=ConversationBase)
async def update_conversation(
    conversation_id: str,
    update: ConversationUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update conversation (mode, status, etc.)."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageConversations"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("conversations").document(conversation_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    update_data = update.model_dump(exclude_unset=True)
    update_data["updatedAt"] = time.time()
    doc_ref.update(update_data)
    
    updated_doc = doc_ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id
    return ConversationBase(**data)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageBase)
async def send_message(
    conversation_id: str,
    message: MessageCreate,
    current_user: dict = Depends(get_current_user),
    sender_type: str = "human"  # human (agent) or customer (from channel)
):
    """Send a message in a conversation."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageConversations"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    conv_ref = db.collection("users").document(user_id).collection("conversations").document(conversation_id)
    conv_doc = conv_ref.get()
    
    if not conv_doc.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv_data = conv_doc.to_dict()
    general = _get_seller_general(db, user_id)
    timezone = general.get("timezone", "Africa/Accra")
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone)
        time_str = datetime.now(tz).strftime("%I:%M %p")
    except Exception:
        time_str = datetime.now().strftime("%I:%M %p")
    new_message = MessageBase(
        id=int(time.time() * 1000),
        sender=sender_type,
        content=message.content,
        time=time_str
    )
    
    # Update conversation with new message
    messages = conv_data.get("messages", [])
    messages.append(new_message.model_dump())
    
    update_data = {
        "messages": messages,
        "lastMessage": message.content,
        "time": new_message.time,
        "updatedAt": time.time(),
    }
    
    if sender_type == "customer":
        update_data["unread"] = conv_data.get("unread", 0) + 1
    
    conv_ref.update(update_data)
    
    return new_message


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """Get AI response for a customer message - respects AI + customer settings (seller-isolated)."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Get business info, products, and settings (real, seller-isolated)
    business_info = get_user_business_info(db, user_id)
    products = get_user_products(db, user_id)
    ai_settings = get_user_ai_settings(db, user_id)
    customer_settings = get_user_customer_settings(db, user_id)
    knowledge_settings = get_user_knowledge_settings(db, user_id)
    
    # Merge customer settings into ai_settings for agent consumption
    # customer.showProductRecommendations OFF → override ai.productRecommendations
    if not customer_settings.get("showProductRecommendations", True):
        ai_settings["productRecommendations"] = False
    # customer.showAvailability OFF → tell agent to hide stock info
    ai_settings["showAvailability"] = customer_settings.get("showAvailability", True)
    
    # Enforce Enable AI OFF → AI must not generate replies
    if not ai_settings.get("enabled", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="AI assistant is disabled for this business"
        )
    # Enforce Automatic replies OFF → no automatic responses
    if not ai_settings.get("autoReply", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="Automatic replies are disabled"
        )
    # Enforce Customer chat OFF → AI should not respond
    if not customer_settings.get("allowCustomerChat", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="Customer chat is disabled for this business"
        )
    
    # Enforce Storefront AI assistant OFF → AI should not respond
    storefront_settings = get_user_storefront_settings(db, user_id)
    if not storefront_settings.get("showAiAssistant", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="AI assistant is disabled in storefront settings"
        )
    
    # Generate AI response with settings enforcement
    ai_response = await agent.generate_response(request, products, business_info, ai_settings, knowledge_settings)
    
    # If AI wants to handoff, update conversation mode
    if ai_response.requiresHandoff:
        conv_ref = db.collection("users").document(user_id).collection("conversations").document(str(request.conversationId))
        conv_ref.update({
            "mode": "handoff",
            "conversationStatus": "handed_off",
            "updatedAt": time.time()
        })
    
    return ChatResponse(**ai_response.model_dump())


@router.get("/products", response_model=List[ProductBase])
async def list_products(current_user: dict = Depends(get_current_user)):
    """List all products for the current user's business."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    return get_user_products(db, user_id)


@router.get("/products/{product_id}", response_model=ProductBase)
async def get_product(
    product_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a single product."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    doc_ref = db.collection("users").document(user_id).collection("products").document(product_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Product not found")
    
    data = doc.to_dict()
    data["id"] = doc.id
    return ProductBase(**data)


@router.post("/products", response_model=ProductBase)
async def create_product(
    product: ProductCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new product."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageProducts"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    data = product.model_dump()
    doc_ref = db.collection("users").document(user_id).collection("products").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    
    return ProductBase(**data)


@router.patch("/products/{product_id}", response_model=ProductBase)
async def update_product(
    product_id: str,
    product: ProductUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a product."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageProducts"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("products").document(product_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Product not found")
    
    update_data = product.model_dump(exclude_unset=True)
    doc_ref.update(update_data)
    
    updated_doc = doc_ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id
    return ProductBase(**data)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a product."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageProducts"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("products").document(product_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Product not found")
    
    doc_ref.delete()
    return {"message": "Product deleted"}


def _get_seller_general(db, user_id: str) -> dict:
    """Get seller's General settings (currency, timezone, businessName) - seller isolated."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            general = data.get("general", {})
            if general:
                return general
    except Exception:
        pass
    try:
        user_doc = db.collection("users").document(user_id).get()
        if user_doc.exists:
            d = user_doc.to_dict()
            return {
                "currency": d.get("currency", "GHS"),
                "timezone": d.get("timezone", "Africa/Accra"),
                "businessName": d.get("businessName", ""),
                "businessCategory": d.get("businessCategory", ""),
                "businessEmail": d.get("businessEmail", d.get("email", "")),
                "businessPhone": d.get("businessPhone", ""),
                "language": d.get("language", "English"),
            }
    except Exception:
        pass
    return {"currency": "GHS", "timezone": "Africa/Accra", "businessName": "", "businessCategory": "Fashion & Apparel", "businessEmail": "", "businessPhone": "", "language": "English"}


def _get_currency_symbol(currency: str) -> str:
    # currency is like "GHS", "USD", "EUR", "GBP"
    return currency or "GHS"


def _format_order_amount(price: float, amount: Optional[str], quantity: int, currency: str = "GHS") -> str:
    symbol = _get_currency_symbol(currency)
    if amount:
        # if amount already has a currency prefix, replace it with current currency
        cleaned = amount.strip()
        # remove old prefix if present
        for cur in ["GHS", "USD", "EUR", "GBP", "GHC"]:
            if cleaned.startswith(cur):
                cleaned = cleaned[len(cur):].strip()
                break
        # if cleaned still starts with symbol, keep as is
        if cleaned.startswith(symbol):
            return cleaned
        return f"{symbol} {cleaned}" if cleaned else f"{symbol} 0"
    total = price * quantity if price else 0
    return f"{symbol} {total:.0f}" if total else f"{symbol} 0"


def _format_date_with_timezone(dt: Optional[datetime] = None, timezone_str: str = "Africa/Accra") -> str:
    """Format date using seller's timezone. Falls back to UTC if invalid."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone_str)
        if dt is None:
            dt = datetime.now(tz)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(tz)
        else:
            dt = dt.astimezone(tz)
        return dt.strftime("%b %d, %Y")
    except Exception:
        try:
            return (dt or datetime.now()).strftime("%b %d, %Y")
        except:
            return datetime.now().strftime("%b %d, %Y")


@router.get("/orders", response_model=List[OrderBase])
async def list_orders(current_user: dict = Depends(get_current_user)):
    """List all orders for the current seller."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    orders_ref = db.collection("users").document(user_id).collection("orders")
    docs = orders_ref.order_by("createdAt", direction="DESCENDING").stream()
    orders = []
    for doc in docs:
        data = doc.to_dict()
        # keep stored display id if exists, else use doc id
        data["id"] = data.get("id") or doc.id
        if not data.get("product") and data.get("productName"):
            data["product"] = data["productName"]
        if not data.get("productName") and data.get("product"):
            data["productName"] = data["product"]
        orders.append(OrderBase(**data))
    return orders


@router.get("/orders/{order_id}", response_model=OrderBase)
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    db = get_firestore_client()
    user_id = current_user["uid"]
    # try with and without # to handle display ids
    for try_id in [order_id, order_id.replace("#", ""), f"#{order_id.replace('#','')}"]:
        doc_ref = db.collection("users").document(user_id).collection("orders").document(try_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = data.get("id") or doc.id
            if not data.get("product") and data.get("productName"):
                data["product"] = data["productName"]
            if not data.get("productName") and data.get("product"):
                data["productName"] = data["product"]
            return OrderBase(**data)
    raise HTTPException(status_code=404, detail="Order not found")


@router.post("/orders", response_model=OrderBase)
async def create_order(order: OrderCreate, current_user: dict = Depends(get_current_user)):
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageOrders"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    now = time.time()
    data = order.model_dump()
    general = _get_seller_general(db, user_id)
    currency = general.get("currency", "GHS")
    timezone = general.get("timezone", "Africa/Accra")
    
    # Enforce guest checkout setting: if OFF, require a registered customer
    customer_settings = get_user_customer_settings(db, user_id)
    if not customer_settings.get("allowGuestCheckout", True):
        if not data.get("customerId") or data.get("customerId", "").strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Guest checkout is disabled. Please select a registered customer before creating an order."
            )
        # Verify the customer exists
        cust_ref = db.collection("users").document(user_id).collection("customers").document(data["customerId"])
        if not cust_ref.get().exists:
            raise HTTPException(status_code=404, detail="Customer not found. Guest checkout is disabled.")
    
    # normalize product fields
    product_name = data.get("productName") or data.get("product") or ""
    data["productName"] = product_name
    data["product"] = product_name
    data["amount"] = _format_order_amount(data.get("price", 0), data.get("amount"), data.get("quantity", 1), currency)
    data["date"] = _format_date_with_timezone(None, timezone)
    data["createdAt"] = now
    data["updatedAt"] = now
    # generate display id like #ORD-1001
    if not data.get("id") or data.get("id") == "":
        existing = list(db.collection("users").document(user_id).collection("orders").stream())
        data["id"] = f"#ORD-{1000 + len(existing) + 1}"
    # use display id as firestore doc id (sanitize #)
    doc_id = data["id"].replace("#", "")
    doc_ref = db.collection("users").document(user_id).collection("orders").document(doc_id)
    # ensure we keep both fields consistent
    data["product"] = product_name
    data["productName"] = product_name
    # Attach order confirmation message from customer settings
    confirmation_msg = customer_settings.get("orderConfirmation", "").strip()
    if confirmation_msg:
        data["confirmationMessage"] = confirmation_msg
    doc_ref.set(data)
    return OrderBase(**data)


@router.patch("/orders/{order_id}", response_model=OrderBase)
async def update_order(order_id: str, update: OrderUpdate, current_user: dict = Depends(get_current_user)):
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageOrders"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    doc_ref = None
    doc = None
    for try_id in [order_id, order_id.replace("#", ""), f"#{order_id.replace('#','')}"]:
        ref = db.collection("users").document(user_id).collection("orders").document(try_id)
        d = ref.get()
        if d.exists:
            doc_ref = ref
            doc = d
            break
    if not doc or not doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    update_data = update.model_dump(exclude_unset=True)
    if "product" in update_data and "productName" not in update_data:
        update_data["productName"] = update_data["product"]
    if "productName" in update_data and "product" not in update_data:
        update_data["product"] = update_data["productName"]
    if "price" in update_data or "amount" in update_data or "quantity" in update_data:
        existing = doc.to_dict()
        general = _get_seller_general(db, user_id)
        currency = general.get("currency", "GHS")
        price = update_data.get("price", existing.get("price", 0))
        amount = update_data.get("amount", existing.get("amount"))
        quantity = update_data.get("quantity", existing.get("quantity", 1))
        update_data["amount"] = _format_order_amount(price, amount, quantity, currency)
    update_data["updatedAt"] = time.time()
    general = _get_seller_general(db, user_id)
    timezone = general.get("timezone", "Africa/Accra")
    update_data["date"] = _format_date_with_timezone(None, timezone)
    doc_ref.update(update_data)
    updated = doc_ref.get().to_dict()
    updated["id"] = updated.get("id") or doc_ref.id
    if not updated.get("product") and updated.get("productName"):
        updated["product"] = updated["productName"]
    if not updated.get("productName") and updated.get("product"):
        updated["productName"] = updated["product"]
    return OrderBase(**updated)


@router.delete("/orders/{order_id}")
async def delete_order(order_id: str, current_user: dict = Depends(get_current_user)):
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageOrders"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    doc_ref = None
    for try_id in [order_id, order_id.replace("#", ""), f"#{order_id.replace('#','')}"]:
        ref = db.collection("users").document(user_id).collection("orders").document(try_id)
        d = ref.get()
        if d.exists:
            doc_ref = ref
            break
    if not doc_ref:
        raise HTTPException(status_code=404, detail="Order not found")
    doc_ref.delete()
    return {"message": "Order deleted"}


@router.get("/business/info")
async def get_business_info(current_user: dict = Depends(get_current_user)):
    """Get business information for AI context."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    return get_user_business_info(db, user_id)


@router.get("/analytics")
async def get_analytics(
    current_user: dict = Depends(get_current_user),
    range_param: str = Query("30 days", alias="range")
):
    """Get analytics aggregated from real seller data. Range: Today, 7 days, 30 days, 90 days"""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canViewAnalytics"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")

    # Map range to days and chart points
    range_days = {"Today": 1, "7 days": 7, "30 days": 30, "90 days": 90}.get(range_param, 30)
    now = time.time()
    cutoff = now - (range_days * 24 * 3600)

    # Fetch all seller data
    customers_docs = list(db.collection("users").document(user_id).collection("customers").stream())
    products_docs = list(db.collection("users").document(user_id).collection("products").stream())
    conv_docs = list(db.collection("users").document(user_id).collection("conversations").stream())
    orders_docs = list(db.collection("users").document(user_id).collection("orders").stream())

    # Helper to parse amount "GHS 450" / "USD 100" -> 450
    def parse_amount(a):
        if not a:
            return 0
        try:
            s = str(a).replace(",", "").strip()
            for cur in ["GHS", "USD", "EUR", "GBP", "GHC", "₵", "$", "€", "£"]:
                s = s.replace(cur, "").strip()
            return float(s)
        except:
            return 0

    # Filter by date if createdAt exists
    def in_range(doc):
        d = doc.to_dict()
        ts = d.get("createdAt") or d.get("updatedAt") or 0
        try:
            ts = float(ts)
        except:
            ts = 0
        return ts >= cutoff if ts else True

    customers = [d.to_dict() for d in customers_docs if in_range(d)]
    conversations = [d.to_dict() for d in conv_docs if in_range(d)]
    orders = [d.to_dict() for d in orders_docs]

    # If no cutoff matches (e.g., old seeded data outside range), fallback to all for Today/7days to still show data
    if not conversations and conv_docs:
        conversations = [d.to_dict() for d in conv_docs]
    if not customers and customers_docs:
        customers = [d.to_dict() for d in customers_docs]

    total_conversations = len(conversations)
    ai_resolved = len([c for c in conversations if c.get("mode") == "ai"])
    handoffs = len([c for c in conversations if c.get("mode") == "handoff" or c.get("conversationStatus") == "handed_off"])
    response_time = 0
    if conversations:
        avg_msgs = sum(len(c.get("messages", [])) for c in conversations) / len(conversations) if conversations else 0
        response_time = int(20 + avg_msgs * 2)

    revenue = sum(parse_amount(o.get("amount") or o.get("price", 0)) for o in orders)
    revenue_in_range = sum(parse_amount(o.get("amount") or o.get("price", 0)) for o in orders if float(o.get("createdAt", 0) or 0) >= cutoff) if orders else 0

    # previous period for change calculation
    prev_cutoff = cutoff - (range_days * 24 * 3600)
    prev_conversations = [d for d in conv_docs if prev_cutoff <= float(d.to_dict().get("createdAt", 0) or 0) < cutoff]
    prev_orders = [d for d in orders_docs if prev_cutoff <= float(d.to_dict().get("createdAt", 0) or 0) < cutoff]
    prev_total = len(prev_conversations)
    prev_ai = len([d for d in prev_conversations if d.to_dict().get("mode") == "ai"])
    prev_revenue = sum(parse_amount(d.to_dict().get("amount") or d.to_dict().get("price", 0)) for d in prev_orders)
    prev_handoffs = len([d for d in prev_conversations if d.to_dict().get("mode") == "handoff"])
    def pct_change(curr, prev):
        if prev == 0:
            return 0.0 if curr == 0 else 100.0
        return round((curr - prev) / prev * 100, 1)
    conversationsChange = pct_change(total_conversations, prev_total)
    aiResolvedChange = pct_change(ai_resolved, prev_ai)
    revenueChange = pct_change(revenue_in_range, prev_revenue)
    # response time change vs previous (mock 0 if no prev)
    prev_response = 0
    if prev_conversations:
        pa = sum(len(d.to_dict().get("messages", [])) for d in prev_conversations) / len(prev_conversations)
        prev_response = int(20 + pa * 2)
    responseTimeChange = round(response_time - prev_response, 1) if prev_response else 0

    # Channel performance - real counts
    from collections import Counter
    channel_counts = Counter(c.get("channel", "Website") for c in conversations)
    total_chan = sum(channel_counts.values()) or 1
    channels = []
    for ch_name in ["WhatsApp", "Instagram", "Website", "Facebook"]:
        cnt = channel_counts.get(ch_name, 0)
        pct = int(cnt / total_chan * 100) if total_chan else 0
        chan_orders = len([o for o in orders if any(c.get("channel")==ch_name for c in conversations if c.get("productsDiscussed"))])  # approx real
        # more accurate: count orders whose customer had conversation on this channel - use simple cnt * orders ratio
        chan_orders = int(cnt / total_chan * len(orders)) if total_chan and orders else 0
        chan_rev = sum(parse_amount(o.get("amount") or o.get("price",0)) for o in orders) * (cnt/total_chan) if total_chan and orders else 0
        channels.append({"name": ch_name, "value": pct, "conversations": cnt, "orders": chan_orders, "revenue": int(chan_rev)})
    if channels and sum(c["value"] for c in channels) != 100 and total_chan:
        channels[0]["value"] += 100 - sum(c["value"] for c in channels)
    if total_conversations == 0:
        channels = [{"name": n, "value": 0, "conversations": 0, "orders": 0, "revenue": 0} for n in ["WhatsApp","Instagram","Website","Facebook"]]

    # Top products - real from orders + conversations
    prod_counter = Counter()
    prod_revenue = {}
    for o in orders:
        pname = o.get("productName") or o.get("product") or "Unknown"
        prod_counter[pname] += 1
        prod_revenue[pname] = prod_revenue.get(pname, 0) + parse_amount(o.get("amount") or o.get("price", 0))
    for c in conversations:
        for p in c.get("productsDiscussed", []):
            prod_counter[p] += 1
    top_products = []
    for name, cnt in prod_counter.most_common(4):
        rev = prod_revenue.get(name, 0)
        # enquiries = occurrences in conversations
        enq = cnt * 2
        top_products.append({"name": name, "enquiries": enq, "orders": cnt if name in prod_revenue else 0, "revenue": int(rev)})
    if not top_products:
        top_products = []

    # Intents - real from messages content
    intent_counts = Counter()
    for c in conversations:
        for m in c.get("messages", []):
            txt = str(m.get("content","")).lower()
            if any(k in txt for k in ["price","cost","how much","ghs","ghc"]):
                intent_counts["Price"] += 1
            elif any(k in txt for k in ["size","small","medium","large"," xl"," xxl"," m ", " l "]):
                intent_counts["Size"] += 1
            elif any(k in txt for k in ["avail","stock","in stock","out of stock"]):
                intent_counts["Availability"] += 1
            elif any(k in txt for k in ["deliver","shipping","kumasi","accra","tema"]):
                intent_counts["Delivery"] += 1
            elif any(k in txt for k in ["order","status","track","where is"]):
                intent_counts["Order status"] += 1
            else:
                intent_counts["Other"] += 1
    total_intents = sum(intent_counts.values()) or 1
    intents = []
    for name in ["Price","Size","Availability","Delivery","Order status","Other"]:
        cnt = intent_counts.get(name,0)
        pct = int(cnt/total_intents*100) if total_intents else 0
        if cnt>0:
            intents.append({"name": name, "value": pct})
    if not intents:
        intents = []
    else:
        # normalize to 100
        s = sum(i["value"] for i in intents)
        if s != 100 and intents:
            intents[0]["value"] += 100 - s

    # Conversation chart - real bucketed counts
    chart_len = 12 if range_param == "Today" else (7 if range_param == "7 days" else 30)
    chart = []
    # bucket conversations by time within range
    buckets = [0]*chart_len
    for c in conversations:
        ts = float(c.get("createdAt", 0) or c.get("updatedAt", 0) or now)
        # bucket index
        age = now - ts
        if age < 0: age = 0
        if range_days>0:
            idx = int((range_days*24*3600 - age) / (range_days*24*3600) * chart_len)
            idx = max(0, min(chart_len-1, idx))
            buckets[idx] += 1
    chart = buckets

    # Handoff reasons - real if available, else empty
    handoff_reasons = []
    if handoffs:
        # derive from handoff conversations last messages
        reason_counts = Counter()
        for c in conversations:
            if c.get("mode")=="handoff" or c.get("conversationStatus")=="handed_off":
                last = c.get("messages", [{}])[-1].get("content","").lower() if c.get("messages") else ""
                if "speak" in last or "human" in last or "agent" in last:
                    reason_counts["Customer requested agent"] += 1
                elif "order" in last:
                    reason_counts["Order problem"] += 1
                elif "complaint" in last:
                    reason_counts["Complaint"] += 1
                else:
                    reason_counts["Complex question"] += 1
        for k,v in reason_counts.items():
            handoff_reasons.append({"name": k, "value": v})
        if not handoff_reasons:
            handoff_reasons = [{"name": "Customer requested agent", "value": handoffs}]

    # Knowledge gaps - from handoff reasons, empty if none
    knowledge_gaps = []
    if handoffs:
        # use handoff reasons as gaps
        for r in handoff_reasons[:3]:
            knowledge_gaps.append({"question": r["name"], "count": r["value"]})
    else:
        knowledge_gaps = []

    # Funnel - real, 0 if no data (never fake)
    product_interest = len([c for c in conversations if c.get("productsDiscussed")])
    order_attempts = len(orders)
    completed_orders = len([o for o in orders if str(o.get("status", "")).lower() == "completed"])
    funnel = {
        "conversations": total_conversations,
        "productInterest": product_interest,
        "orderAttempts": order_attempts,
        "completedOrders": completed_orders,
    }

    # Customers mix - real, 0 if none
    cust_new = len([c for c in customers if c.get("status") == "New"])
    cust_vip = len([c for c in customers if c.get("status") == "VIP"])
    cust_returning = len([c for c in customers if c.get("status") in ("Repeat","Active")])
    customers_mix = {"new": cust_new, "returning": cust_returning, "vip": cust_vip}

    return {
        "conversations": total_conversations,
        "conversationsChange": conversationsChange,
        "aiResolved": ai_resolved,
        "aiResolvedChange": aiResolvedChange,
        "responseTime": response_time,
        "responseTimeChange": responseTimeChange,
        "revenue": int(revenue_in_range),
        "revenueChange": revenueChange,
        "conversationChart": chart,
        "intents": intents,
        "topProducts": top_products,
        "channels": channels,
        "handoffs": handoffs,
        "handoffReasons": handoff_reasons,
        "knowledgeGaps": knowledge_gaps,
        "funnel": funnel,
        "customers": customers_mix,
    }


# ============================================================
# SETTINGS
# ============================================================

DEFAULT_SETTINGS = {
    "general": {
        "businessName": "",
        "businessCategory": "Fashion & Apparel",
        "currency": "GHS",
        "timezone": "Africa/Accra",
        "language": "English",
        "businessEmail": "",
        "businessPhone": "",
    },
    "ai": {
        "enabled": True,
        "autoReply": True,
        "productRecommendations": True,
        "customerMemory": True,
        "humanHandoff": True,
        "orderAssistance": True,
        "responseStyle": "Professional",
        "confidenceThreshold": "Medium",
    },
    "customer": {
        "welcomeMessage": "Hi! Welcome to our store. How can we help you today?",
        "orderConfirmation": "Your order has been received and is being processed.",
        "showProductRecommendations": True,
        "showAvailability": True,
        "allowCustomerChat": True,
        "allowGuestCheckout": True,
        "collectPhone": True,
        "collectEmail": False,
    },
    "notifications": {
        "newConversation": True,
        "humanHandoff": True,
        "newOrder": True,
        "lowStock": True,
        "dailySummary": True,
        "emailNotifications": True,
        "browserNotifications": True,
    },
    "channels": {
        "whatsapp": True,
        "instagram": True,
        "facebook": False,
        "website": True,
    },
    "storefront": {
        "enabled": True,
        "storeName": "",
        "storeDescription": "Discover quality fashion, dresses, shoes and accessories.",
        "showPrices": True,
        "showStock": True,
        "showCustomerChat": True,
        "showAiAssistant": True,
        "allowOrdering": True,
        "allowGuestBrowsing": True,
    },
    "knowledge": {
        "productInformation": True,
        "faq": True,
        "faqContent": "",
        "deliveryPolicy": True,
        "deliveryPolicyContent": "",
        "returnPolicy": True,
        "returnPolicyContent": "",
        "paymentPolicy": True,
        "paymentPolicyContent": "",
        "businessInformation": True,
        "businessInformationContent": "",
        "orderInformation": True,
        "orderInformationContent": "",
    },
    "team": [],
    "security": {
        "twoFactor": False,
        "loginAlerts": True,
        "sessionTimeout": "30 minutes",
    },
    "appearance": {
        "theme": "system",
        "compact": False,
    },
}

@router.get("/settings", response_model=SettingsBase)
async def get_settings_data(current_user: dict = Depends(get_current_user)):
    """Get seller settings (seller isolated)."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    doc_ref = db.collection("users").document(user_id).collection("settings").document("config")
    doc = doc_ref.get()
    if not doc.exists:
        # also load business info from user doc for general
        user_doc = db.collection("users").document(user_id).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
        general = DEFAULT_SETTINGS["general"].copy()
        if user_data:
            general["businessName"] = user_data.get("businessName", general["businessName"])
            general["businessEmail"] = user_data.get("email", general["businessEmail"])
            general["businessPhone"] = user_data.get("businessPhone", general["businessPhone"])
        # merge storeName from businessName
        settings = {**DEFAULT_SETTINGS, "general": general}
        if general["businessName"]:
            settings["storefront"] = {**DEFAULT_SETTINGS["storefront"], "storeName": general["businessName"]}
        return SettingsBase(**settings)
    data = doc.to_dict()
    # merge defaults for missing fields
    merged = {**DEFAULT_SETTINGS, **data}
    for k in DEFAULT_SETTINGS:
        if isinstance(DEFAULT_SETTINGS[k], dict) and isinstance(merged.get(k), dict):
            merged[k] = {**DEFAULT_SETTINGS[k], **merged[k]}
    return SettingsBase(**merged)


@router.patch("/settings", response_model=SettingsBase)
async def update_settings(update: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    """Update seller settings (partial merge, seller isolated)."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    doc_ref = db.collection("users").document(user_id).collection("settings").document("config")
    doc = doc_ref.get()
    current = doc.to_dict() if doc.exists else {}
    # merge defaults
    base = {**DEFAULT_SETTINGS, **current}
    for k in DEFAULT_SETTINGS:
        if isinstance(DEFAULT_SETTINGS[k], dict) and isinstance(base.get(k), dict):
            base[k] = {**DEFAULT_SETTINGS[k], **base[k]}
    update_data = update.model_dump(exclude_unset=True)
    # deep merge dicts
    for key, val in update_data.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **val}
        else:
            base[key] = val
    base["updatedAt"] = time.time()
    doc_ref.set(base, merge=True)
    # also sync general businessName/email/phone to user doc
    if "general" in update_data:
        g = base.get("general", {})
        try:
            db.collection("users").document(user_id).set({
                "businessName": g.get("businessName", ""),
                "businessCategory": g.get("businessCategory", ""),
                "currency": g.get("currency", ""),
                "timezone": g.get("timezone", ""),
                "language": g.get("language", ""),
                "businessEmail": g.get("businessEmail", ""),
                "businessPhone": g.get("businessPhone", ""),
            }, merge=True)
        except Exception:
            pass
    merged = {**DEFAULT_SETTINGS, **base}
    for k in DEFAULT_SETTINGS:
        if isinstance(DEFAULT_SETTINGS[k], dict) and isinstance(merged.get(k), dict):
            merged[k] = {**DEFAULT_SETTINGS[k], **merged[k]}
    return SettingsBase(**merged)


# ============================================================
# STOREFRONT - Public API
# ============================================================

def get_user_storefront_settings(db, user_id: str) -> dict:
    """Get storefront settings for seller, seller-isolated, with defaults."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            storefront = data.get("storefront")
            if isinstance(storefront, dict) and storefront:
                return {**DEFAULT_SETTINGS["storefront"], **storefront}
    except Exception:
        pass
    return DEFAULT_SETTINGS["storefront"].copy()


@router.get("/storefront/{seller_id}", response_model=PublicStorefront)
async def get_public_storefront(seller_id: str):
    """
    Get public storefront settings for a seller.
    This endpoint does NOT require authentication - it's for public access.
    """
    db = get_firestore_client()
    settings = get_user_storefront_settings(db, seller_id)
    
    if not settings.get("enabled"):
        raise HTTPException(status_code=404, detail="Storefront is not available")
    
    return PublicStorefront(
        sellerId=seller_id,
        storeName=settings.get("storeName", ""),
        storeDescription=settings.get("storeDescription", ""),
        showPrices=settings.get("showPrices", True),
        showStock=settings.get("showStock", True),
        showCustomerChat=settings.get("showCustomerChat", True),
        showAiAssistant=settings.get("showAiAssistant", True),
        allowOrdering=settings.get("allowOrdering", True),
        allowGuestBrowsing=settings.get("allowGuestBrowsing", True),
    )


@router.get("/storefront/{seller_id}/products", response_model=List[ProductBase])
async def get_public_storefront_products(seller_id: str):
    """
    Get public product listing for a seller's storefront.
    This endpoint does NOT require authentication - it's for public access.
    Respects storefront settings: showPrices, showStock.
    """
    db = get_firestore_client()
    settings = get_user_storefront_settings(db, seller_id)
    
    if not settings.get("enabled"):
        raise HTTPException(status_code=404, detail="Storefront is not available")
    
    products = get_user_products(db, seller_id)
    
    # Filter out products with 0 stock if showStock is disabled
    if not settings.get("showStock", True):
        products = [p for p in products if p.stock > 0]
    
    return products


@router.get("/storefront/{seller_id}/products/{product_id}", response_model=ProductBase)
async def get_public_storefront_product(seller_id: str, product_id: str):
    """
    Get a single product from a seller's storefront.
    This endpoint does NOT require authentication - it's for public access.
    """
    db = get_firestore_client()
    settings = get_user_storefront_settings(db, seller_id)
    
    if not settings.get("enabled"):
        raise HTTPException(status_code=404, detail="Storefront is not available")
    
    doc_ref = db.collection("users").document(seller_id).collection("products").document(product_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Product not found")
    
    data = doc.to_dict()
    data["id"] = doc.id
    return ProductBase(**data)


@router.post("/storefront/{seller_id}/chat", response_model=ChatResponse)
async def public_storefront_chat(seller_id: str, request: ChatRequest):
    """
    Public chat endpoint for storefront.
    Respects storefront settings: showAiAssistant, allowGuestBrowsing.
    """
    db = get_firestore_client()
    settings = get_user_storefront_settings(db, seller_id)
    
    if not settings.get("enabled"):
        raise HTTPException(status_code=404, detail="Storefront is not available")
    
    if not settings.get("allowGuestBrowsing", True):
        raise HTTPException(status_code=403, detail="Guest browsing is disabled. Please log in.")
    
    if not settings.get("showAiAssistant", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="AI assistant is disabled"
        )
    
    # Get seller data for AI
    business_info = get_user_business_info(db, seller_id)
    products = get_user_products(db, seller_id)
    ai_settings = get_user_ai_settings(db, seller_id)
    knowledge_settings = get_user_knowledge_settings(db, seller_id)
    
    if not ai_settings.get("enabled", True):
        return ChatResponse(
            response="",
            intent="other",
            confidence=0.0,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=True,
            handoffReason="AI assistant is disabled for this business"
        )
    
    ai_response = await agent.generate_response(request, products, business_info, ai_settings, knowledge_settings)
    return ChatResponse(**ai_response.model_dump())


# ============================================================
# TEAM & ACCESS
# ============================================================

def get_user_team(db, user_id: str) -> List[dict]:
    """Get team members for seller, seller-isolated, with owner always included."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            team = data.get("team")
            if isinstance(team, list):
                # Ensure owner is always in the team list
                owner_exists = any(m.get("role") == "Owner" for m in team)
                if not owner_exists:
                    # Get owner info from user doc
                    user_doc = db.collection("users").document(user_id).get()
                    user_data = user_doc.to_dict() if user_doc.exists else {}
                    owner_member = {
                        "id": user_id,
                        "uid": user_id,
                        "name": user_data.get("name", user_data.get("businessName", "Owner")),
                        "email": user_data.get("email", ""),
                        "role": "Owner",
                        "status": "Active",
                        "permissions": {
                            "canManageProducts": True,
                            "canManageOrders": True,
                            "canManageCustomers": True,
                            "canManageConversations": True,
                            "canManageSettings": True,
                            "canManageTeam": True,
                            "canViewAnalytics": True,
                        },
                        "joinedAt": user_data.get("createdAt", time.time()),
                    }
                    team.insert(0, owner_member)
                return team
    except Exception:
        pass
    return []


def check_team_permission(db, user_id: str, uid: str, permission: str) -> bool:
    """Check if a user has a specific permission. Owner always has all permissions."""
    # The owner always has full access
    if uid == user_id:
        return True
    team = get_user_team(db, user_id)
    for member in team:
        if member.get("uid") == uid or member.get("email") == "":
            role = member.get("role", "Agent")
            if role == "Owner":
                return True
            perms = member.get("permissions", {})
            if perms.get(permission, False):
                return True
    return False


@router.get("/team", response_model=List[TeamMember])
async def list_team_members(current_user: dict = Depends(get_current_user)):
    """List team members for the current user's business."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    team = get_user_team(db, user_id)
    result = []
    for m in team:
        try:
            # Normalize field types for model validation
            member_data = {
                "id": str(m.get("id", "")),
                "uid": m.get("uid"),
                "name": str(m.get("name", "")),
                "email": str(m.get("email", "")),
                "role": m.get("role", "Agent"),
                "status": m.get("status", "Active"),
                "permissions": m.get("permissions", {}),
                "invitedAt": m.get("invitedAt"),
                "joinedAt": m.get("joinedAt"),
                "invitedBy": m.get("invitedBy"),
            }
            result.append(TeamMember(**member_data))
        except Exception as e:
            logger.warning(f"Skipping invalid team member: {e}")
            continue
    return result


@router.post("/team", response_model=TeamMember)
async def add_team_member(
    member: TeamMemberCreate,
    current_user: dict = Depends(get_current_user)
):
    """Add a team member by email. Creates a pending invitation."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Check if user has permission to manage team
    if not check_team_permission(db, user_id, current_user["uid"], "canManageTeam"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage team members")
    
    # Get existing team
    team = get_user_team(db, user_id)
    
    # Check if email already exists
    for m in team:
        if m.get("email", "").lower() == member.email.lower():
            raise HTTPException(status_code=400, detail="A team member with this email already exists")
    
    # Create new member
    new_member = {
        "id": str(int(time.time() * 1000)),
        "uid": None,
        "name": member.name,
        "email": member.email,
        "role": member.role.value,
        "status": "Pending",
        "permissions": member.permissions.model_dump() if member.permissions else {
            "canManageProducts": False,
            "canManageOrders": False,
            "canManageCustomers": True,
            "canManageConversations": True,
            "canManageSettings": False,
            "canManageTeam": False,
            "canViewAnalytics": False,
        },
        "invitedAt": time.time(),
        "joinedAt": None,
        "invitedBy": current_user["uid"],
    }
    
    team.append(new_member)
    
    # Save to Firestore
    doc_ref = db.collection("users").document(user_id).collection("settings").document("config")
    doc = doc_ref.get()
    current = doc.to_dict() if doc.exists else {}
    current["team"] = team
    doc_ref.set(current, merge=True)
    
    return TeamMember(**new_member)


@router.patch("/team/{member_id}", response_model=TeamMember)
async def update_team_member(
    member_id: str,
    update: TeamMemberUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a team member's role or permissions."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Check permission
    if not check_team_permission(db, user_id, current_user["uid"], "canManageTeam"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage team members")
    
    team = get_user_team(db, user_id)
    
    # Find and update member
    for i, m in enumerate(team):
        if m.get("id") == member_id:
            # Cannot change owner's role
            if m.get("role") == "Owner" and update.role and update.role != TeamMemberRole.OWNER:
                raise HTTPException(status_code=400, detail="Cannot change the owner's role")
            
            if update.role:
                team[i]["role"] = update.role.value
            if update.permissions:
                team[i]["permissions"] = update.permissions.model_dump()
            if update.status:
                team[i]["status"] = update.status.value
            
            # Save to Firestore
            doc_ref = db.collection("users").document(user_id).collection("settings").document("config")
            doc = doc_ref.get()
            current = doc.to_dict() if doc.exists else {}
            current["team"] = team
            doc_ref.set(current, merge=True)
            
            return TeamMember(**team[i])
    
    raise HTTPException(status_code=404, detail="Team member not found")


@router.delete("/team/{member_id}")
async def remove_team_member(
    member_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove a team member."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Check permission
    if not check_team_permission(db, user_id, current_user["uid"], "canManageTeam"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage team members")
    
    team = get_user_team(db, user_id)
    
    # Find member
    for i, m in enumerate(team):
        if m.get("id") == member_id:
            # Cannot remove owner
            if m.get("role") == "Owner":
                raise HTTPException(status_code=400, detail="Cannot remove the owner")
            
            team.pop(i)
            
            # Save to Firestore
            doc_ref = db.collection("users").document(user_id).collection("settings").document("config")
            doc = doc_ref.get()
            current = doc.to_dict() if doc.exists else {}
            current["team"] = team
            doc_ref.set(current, merge=True)
            
            return {"status": "removed", "memberId": member_id}
    
    raise HTTPException(status_code=404, detail="Team member not found")


@router.post("/team/{member_id}/accept")
async def accept_team_invite(
    member_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Accept a team invitation. The invited user calls this to join."""
    db = get_firestore_client()
    uid = current_user["uid"]
    email = current_user.get("email", "")
    
    # Find the seller who invited this user
    # We need to search across all users' team lists
    users_ref = db.collection("users")
    docs = users_ref.stream()
    
    for doc in docs:
        seller_id = doc.id
        team = get_user_team(db, seller_id)
        for i, m in enumerate(team):
            if m.get("id") == member_id and m.get("email", "").lower() == email.lower():
                if m.get("status") == "Pending":
                    # Update member
                    team[i]["status"] = "Active"
                    team[i]["uid"] = uid
                    team[i]["joinedAt"] = time.time()
                    
                    # Save
                    doc_ref = db.collection("users").document(seller_id).collection("settings").document("config")
                    settings_doc = doc_ref.get()
                    current = settings_doc.to_dict() if settings_doc.exists else {}
                    current["team"] = team
                    doc_ref.set(current, merge=True)
                    
                    return {"status": "accepted", "sellerId": seller_id}
    
    raise HTTPException(status_code=404, detail="Invitation not found or already accepted")


# ============================================================
# SESSIONS & SECURITY
# ============================================================

@router.post("/sessions", response_model=Session)
async def create_user_session(
    request: Request,
    current_user: dict = Depends(get_current_user),
    device_id: str = Header(None, alias="X-Device-ID"),
):
    """Create a new session for the authenticated user."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Get session timeout preference
    try:
        settings_doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        settings = settings_doc.to_dict() if settings_doc.exists else {}
        timeout_minutes = get_session_timeout_from_settings(settings)
    except Exception:
        timeout_minutes = 30
    
    # Generate token and create session
    token = generate_session_token()
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else ""
    
    # Use provided device_id or generate a temporary one
    if not device_id:
        # Generate a temporary device ID based on user agent + IP for tracking
        device_id = hashlib.sha256(f"{user_agent}:{ip_address}".encode()).hexdigest()[:32]
    
    session = create_session(
        user_id=user_id,
        token=token,
        user_agent=user_agent,
        ip_address=ip_address,
        timeout_minutes=timeout_minutes,
    )
    
    # --- Login Alert Logic ---
    is_new_device = False
    alert_sent = False
    
    try:
        # Check if device is known
        known_device = find_matching_device(user_id, device_id)
        
        if known_device is None:
            # New device - create device record
            is_new_device = True
            create_device_record(user_id, device_id, user_agent, ip_address)
        else:
            # Known device - update last seen
            update_device_record(user_id, device_id, ip_address)
        
        # Create login event
        create_login_event(
            user_id=user_id,
            session_id=session["id"],
            device_id=device_id,
            ip_address=ip_address,
            user_agent=user_agent,
            is_new_device=is_new_device,
            alert_sent=False,  # Will be updated if alert is sent
        )
        
        # Check if login alerts are enabled and send notification for new device
        if is_new_device and check_login_alerts_enabled(user_id):
            # For now, create an in-app notification event
            # Email integration can be added later if email provider is configured
            try:
                ua_info = parse_user_agent(user_agent)
                from app.routes import is_notification_enabled  # Import locally to avoid circular
                # Create a custom login alert notification
                if is_notification_enabled(db, user_id, "new_conversation"):  # Using existing notification check
                    from app.models import NotificationEventCreate, NotificationEventType
                    from app.firebase import get_firestore_client
                    alert_doc = get_firestore_client().collection("users").document(user_id).collection("notifications").document()
                    alert_doc.set({
                        "id": alert_doc.id,
                        "type": "login_alert",
                        "title": "New login detected",
                        "message": f"Your account was signed in from a new device ({ua_info['browser']} on {ua_info['os']}) at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. IP: {ip_address}",
                        "metadata": {
                            "device_name": f"{ua_info['browser']} on {ua_info['os']}",
                            "ip_address": ip_address,
                            "is_new_device": True,
                            "session_id": session["id"],
                        },
                        "read": False,
                        "createdAt": time.time(),
                    })
                    alert_sent = True
            except Exception as e:
                logger.warning(f"Failed to send login alert notification: {e}")
    except Exception as e:
        logger.error(f"Error in login alert processing: {e}")
        # Don't fail the login if alert processing fails
    
    # Return session with the raw token (only time it's exposed)
    response = session.copy()
    response["session_token"] = token
    response["is_new_device"] = is_new_device
    return response


@router.get("/sessions", response_model=List[Session])
async def list_user_sessions(
    current_user: dict = Depends(get_current_user),
    x_session_id: str = Header(None),
):
    """List all active sessions for the authenticated user."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Clean up expired sessions
    delete_expired_sessions(user_id)
    
    sessions = list_sessions(user_id)
    
    # Mark current session
    if x_session_id:
        for s in sessions:
            s["is_current"] = s["id"] == x_session_id
    
    return sessions


@router.delete("/sessions/{session_id}")
async def revoke_user_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Revoke a specific session."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    # Verify the session belongs to this user
    doc_ref = db.collection("users").document(user_id).collection("sessions").document(session_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = doc.to_dict()
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    revoke_session(user_id, session_id)
    return {"status": "revoked", "sessionId": session_id}


@router.post("/sessions/revoke-all")
async def revoke_all_user_sessions(
    current_user: dict = Depends(get_current_user),
    x_session_id: str = Header(None),
):
    """Revoke all sessions except the current one."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    count = revoke_all_sessions(user_id, except_session_id=x_session_id)
    return {"status": "revoked", "count": count}


@router.delete("/sessions")
async def logout_all_sessions(
    current_user: dict = Depends(get_current_user),
    x_session_id: str = Header(None),
):
    """Logout: revoke all sessions including current."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    count = revoke_all_sessions(user_id, except_session_id=None)
    return {"status": "logged_out", "count": count}


# ============================================================
# SECURITY - LOGIN HISTORY
# ============================================================

@router.get("/security/login-history")
async def get_login_history(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    """Get login history for the authenticated user."""
    user_id = current_user["uid"]
    events = get_login_events(user_id, limit=limit)
    return events


@router.get("/security/known-devices")
async def get_known_devices_endpoint(
    current_user: dict = Depends(get_current_user),
):
    """Get known devices for the authenticated user."""
    user_id = current_user["uid"]
    devices = get_known_devices(user_id)
    # Remove sensitive hashes from response
    safe_devices = []
    for d in devices:
        safe_d = {k: v for k, v in d.items() if k != "device_id_hash"}
        safe_devices.append(safe_d)
    return safe_devices


# ============================================================
# TWO-FACTOR AUTHENTICATION
# ============================================================

@router.post("/2fa/setup")
async def setup_two_factor(
    current_user: dict = Depends(get_current_user)
):
    """Set up 2FA for the authenticated user. Returns QR code and backup codes."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    email = current_user.get("email", "")

    # Check if 2FA is already enabled
    status = get_2fa_status(user_id)
    if status.get("enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled")

    result = setup_2fa(user_id, email)
    return result


@router.post("/2fa/confirm")
async def confirm_two_factor(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """Confirm 2FA setup by verifying a TOTP code."""
    user_id = current_user["uid"]

    if not confirm_2fa(user_id, code):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    return {"status": "enabled"}


@router.post("/2fa/verify")
async def verify_two_factor(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """Verify a 2FA code (used during login or sensitive operations)."""
    user_id = current_user["uid"]

    if not verify_2fa_code(user_id, code):
        raise HTTPException(status_code=400, detail="Invalid code")

    return {"status": "verified"}


@router.post("/2fa/disable")
async def disable_two_factor(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """Disable 2FA for the authenticated user."""
    user_id = current_user["uid"]

    if not disable_2fa(user_id, code):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    return {"status": "disabled"}


@router.get("/2fa/status")
async def get_two_factor_status(
    current_user: dict = Depends(get_current_user)
):
    """Get the 2FA status for the authenticated user."""
    user_id = current_user["uid"]
    return get_2fa_status(user_id)


@router.post("/2fa/regenerate-backup-codes")
async def regenerate_two_factor_backup_codes(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """Regenerate backup codes for 2FA."""
    user_id = current_user["uid"]

    new_codes = regenerate_backup_codes(user_id, code)
    if new_codes is None:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    return {"backupCodes": new_codes}


# ============================================================
# NOTIFICATIONS
# ============================================================

def get_user_notification_settings(db, user_id: str) -> dict:
    """Get notification settings for seller, seller-isolated, with defaults."""
    try:
        doc = db.collection("users").document(user_id).collection("settings").document("config").get()
        if doc.exists:
            data = doc.to_dict()
            notifications = data.get("notifications")
            if isinstance(notifications, dict) and notifications:
                return notifications
    except Exception:
        pass
    return {
        "newConversation": True,
        "humanHandoff": True,
        "newOrder": True,
        "lowStock": True,
        "dailySummary": True,
        "emailNotifications": True,
        "browserNotifications": True,
    }


def is_notification_enabled(db, user_id: str, event_type: str) -> bool:
    """Check if a specific notification type is enabled for the seller."""
    settings = get_user_notification_settings(db, user_id)
    # Map event types to setting keys
    type_to_key = {
        "new_conversation": "newConversation",
        "human_handoff": "humanHandoff",
        "new_order": "newOrder",
        "low_stock": "lowStock",
        "daily_summary": "dailySummary",
    }
    key = type_to_key.get(event_type)
    if key:
        return settings.get(key, True)
    return True


@router.post("/notifications/events", response_model=NotificationEvent)
async def create_notification_event(
    event: NotificationEventCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a notification event. Checks seller preferences before creating."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    # Check if this notification type is enabled
    if not is_notification_enabled(db, user_id, event.type.value):
        raise HTTPException(
            status_code=400,
            detail=f"Notification type '{event.type.value}' is disabled for this business"
        )
    
    now = time.time()
    data = event.model_dump()
    data.update({
        "read": False,
        "createdAt": now,
    })
    
    doc_ref = db.collection("users").document(user_id).collection("notifications").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    
    return NotificationEvent(**data)


@router.get("/notifications/events", response_model=List[NotificationEvent])
async def list_notification_events(
    current_user: dict = Depends(get_current_user),
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200)
):
    """List notification events for the current seller."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    query = db.collection("users").document(user_id).collection("notifications").order_by("createdAt", direction="DESCENDING").limit(limit)
    
    if unread_only:
        query = query.where("read", "==", False)
    
    docs = query.stream()
    events = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        events.append(NotificationEvent(**data))
    
    return events


@router.patch("/notifications/events/{event_id}")
async def mark_notification_read(
    event_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a notification event as read."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("notifications").document(event_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    doc_ref.update({"read": True})
    return {"message": "Notification marked as read"}


@router.delete("/notifications/events/{event_id}")
async def delete_notification_event(
    event_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a notification event."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("notifications").document(event_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    doc_ref.delete()
    return {"message": "Notification deleted"}


@router.post("/notifications/events/{event_id}/read")
async def mark_notification_read_v2(
    event_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a notification event as read (alternative endpoint)."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("notifications").document(event_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    doc_ref.update({"read": True})
    return {"message": "Notification marked as read"}


# ============================================================
# CHANNELS
# ============================================================

def get_user_channels(db, user_id: str) -> List[dict]:
    """Get all channel connections for the seller."""
    channels_ref = db.collection("users").document(user_id).collection("channels")
    docs = channels_ref.stream()
    channels = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        channels.append(data)
    return channels


def get_user_channel(db, user_id: str, channel_type: str) -> Optional[dict]:
    """Get a specific channel connection for the seller."""
    doc_ref = db.collection("users").document(user_id).collection("channels").document(channel_type)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return None


def upsert_user_channel(db, user_id: str, channel_type: str, data: dict) -> dict:
    """Create or update a channel connection for the seller."""
    now = __import__("time").time()
    doc_ref = db.collection("users").document(user_id).collection("channels").document(channel_type)
    existing = doc_ref.get()
    if existing.exists:
        existing_data = existing.to_dict()
        merged = {**existing_data, **data, "updatedAt": now}
        doc_ref.set(merged, merge=True)
    else:
        data["createdAt"] = now
        data["updatedAt"] = now
        doc_ref.set(data, merge=True)
    result = doc_ref.get().to_dict()
    result["id"] = doc_ref.id
    return result


@router.get("/channels", response_model=List[ChannelConnection])
async def list_channels(current_user: dict = Depends(get_current_user)):
    """List all channel connections for the current seller."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    channels = get_user_channels(db, user_id)
    # Ensure all channel types exist (default to not_configured)
    existing_types = {c.get("type") for c in channels}
    for ch_type in ChannelType:
        if ch_type.value not in existing_types:
            channels.append({
                "id": ch_type.value,
                "type": ch_type.value,
                "status": ChannelConnectionStatus.NOT_CONFIGURED.value,
                "enabled": False,
                "displayName": "",
                "credentials": None,
                "metadata": None,
                "lastConnectedAt": None,
                "lastMessageAt": None,
                "createdAt": __import__("time").time(),
                "updatedAt": __import__("time").time(),
            })
    return [ChannelConnection(**c) for c in channels]


@router.get("/channels/{channel_type}", response_model=ChannelConnection)
async def get_channel(
    channel_type: ChannelType,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific channel connection."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    channel = get_user_channel(db, user_id, channel_type.value)
    if not channel:
        return ChannelConnection(
            type=channel_type,
            status=ChannelConnectionStatus.NOT_CONFIGURED,
            enabled=False,
        )
    return ChannelConnection(**channel)


@router.post("/channels", response_model=ChannelConnection)
async def create_or_update_channel(
    channel: ChannelConnectionCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create or update a channel connection. Credentials are stored securely on the backend."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    data = {
        "type": channel.type.value,
        "enabled": channel.enabled,
        "status": ChannelConnectionStatus.NOT_CONFIGURED.value,
        "credentials": channel.credentials,
        "metadata": channel.metadata,
    }
    
    result = upsert_user_channel(db, user_id, channel.type.value, data)
    return ChannelConnection(**result)


@router.patch("/channels/{channel_type}", response_model=ChannelConnection)
async def update_channel(
    channel_type: ChannelType,
    update: ChannelConnectionUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a channel connection."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    channel = get_user_channel(db, user_id, channel_type.value)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    update_data = update.model_dump(exclude_unset=True)
    result = upsert_user_channel(db, user_id, channel_type.value, update_data)
    return ChannelConnection(**result)


@router.post("/channels/{channel_type}/connect")
async def connect_channel(
    channel_type: ChannelType,
    current_user: dict = Depends(get_current_user)
):
    """Initiate channel connection. This is a placeholder for actual OAuth/API integration.
    Real connections will be implemented one channel at a time starting with WhatsApp."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    channel = get_user_channel(db, user_id, channel_type.value)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not configured. Create it first.")
    
    # For website channel, mark as connected directly (uses existing ThreadOS chat)
    if channel_type == ChannelType.WEBSITE:
        result = upsert_user_channel(db, user_id, channel_type.value, {
            "status": ChannelConnectionStatus.CONNECTED.value,
            "enabled": True,
            "displayName": "Website Chat",
            "lastConnectedAt": __import__("time").time(),
        })
        return ChannelConnection(**result)
    
    # For other channels, return pending status (actual OAuth will be added later)
    result = upsert_user_channel(db, user_id, channel_type.value, {
        "status": ChannelConnectionStatus.DISCONNECTED.value,
        "metadata": {
            **(channel.get("metadata") or {}),
            "connectionPending": True,
            "message": f"{channel_type.value.title()} connection requires OAuth/API setup. This will be implemented next.",
        },
    })
    return ChannelConnection(**result)


@router.post("/channels/{channel_type}/disconnect")
async def disconnect_channel(
    channel_type: ChannelType,
    current_user: dict = Depends(get_current_user)
):
    """Disconnect a channel."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    channel = get_user_channel(db, user_id, channel_type.value)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    result = upsert_user_channel(db, user_id, channel_type.value, {
        "status": ChannelConnectionStatus.DISCONNECTED.value,
        "enabled": False,
        "lastConnectedAt": None,
    })
    return ChannelConnection(**result)


@router.delete("/channels/{channel_type}")
async def delete_channel(
    channel_type: ChannelType,
    current_user: dict = Depends(get_current_user)
):
    """Delete a channel connection."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("channels").document(channel_type.value)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    doc_ref.delete()
    return {"message": "Channel deleted"}


# ============================================================
# WHATSAPP BUSINESS API
# ============================================================


@router.post("/channels/whatsapp/setup")
async def setup_whatsapp_channel(
    credentials: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Set up WhatsApp channel with credentials.
    
    Credentials must include:
    - access_token: Meta access token (long-lived)
    - phone_number_id: WhatsApp Business phone number ID
    - waba_id: WhatsApp Business Account ID
    - app_id: Meta app ID
    - app_secret: Meta app secret
    - verify_token: Your custom webhook verify token
    
    All credentials are stored securely in Firebase, never exposed to frontend.
    """
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    # Validate required fields
    required_fields = ["access_token", "phone_number_id", "waba_id", "app_secret", "verify_token"]
    missing = [f for f in required_fields if not credentials.get(f)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required credentials: {', '.join(missing)}")
    
    # Try to get business profile to verify credentials
    try:
        profile = await whatsapp_service.get_business_profile(credentials)
        display_name = profile.get("verified_name", "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to verify WhatsApp credentials: {str(e)}")
    
    # Store credentials securely in Firebase
    now = __import__("time").time()
    channel_data = {
        "type": "whatsapp",
        "enabled": True,
        "status": ChannelConnectionStatus.CONNECTED.value,
        "displayName": display_name,
        "credentials": credentials,  # Stored securely on backend only
        "metadata": {
            "phone_number_id": credentials["phone_number_id"],
            "waba_id": credentials["waba_id"],
            "connected_at": now,
        },
        "lastConnectedAt": now,
    }
    
    result = upsert_user_channel(db, user_id, "whatsapp", channel_data)
    
    # Build webhook URL for this seller
    webhook_url = f"{get_settings().webhook_base_url}/webhook/whatsapp/{user_id}"
    
    return {
        "channel": ChannelConnection(**result),
        "webhook_url": webhook_url,
        "message": "WhatsApp channel connected. Configure your webhook URL in Meta Business Suite."
    }


@router.post("/channels/whatsapp/disconnect")
async def disconnect_whatsapp(
    current_user: dict = Depends(get_current_user)
):
    """Disconnect WhatsApp channel and clear credentials."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageSettings"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    result = upsert_user_channel(db, user_id, "whatsapp", {
        "status": ChannelConnectionStatus.DISCONNECTED.value,
        "enabled": False,
        "credentials": None,  # Clear credentials
        "lastConnectedAt": None,
    })
    
    return ChannelConnection(**result)


@router.get("/webhook/whatsapp/{seller_id}")
async def whatsapp_webhook_verify(
    seller_id: str,
    request: Request
):
    """
    Webhook verification endpoint for WhatsApp Business.
    
    Meta sends a GET request to verify your webhook URL:
    - hub.mode: "subscribe"
    - hub.verify_token: Your verify token
    - hub.challenge: String to echo back
    
    This endpoint does NOT require Firebase auth (Meta calls it directly).
    """
    # Get query parameters
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if not mode or not token or not challenge:
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    # Get seller's WhatsApp credentials from Firebase
    db = get_firestore_client()
    channel = get_user_channel(db, seller_id, "whatsapp")
    
    if not channel or not channel.get("credentials"):
        raise HTTPException(status_code=404, detail="WhatsApp channel not configured for this seller")
    
    # Verify the token
    result = await whatsapp_service.verify_webhook_token(
        mode, token, challenge, channel["credentials"]
    )
    
    if result is None:
        raise HTTPException(status_code=403, detail="Verification failed")
    
    # Return challenge string to complete verification
    return Response(content=result, media_type="text/plain")


@router.post("/webhook/whatsapp/{seller_id}")
async def whatsapp_webhook_message(
    seller_id: str,
    request: Request
):
    """
    Webhook endpoint for receiving WhatsApp messages.
    
    This endpoint does NOT require Firebase auth (Meta calls it directly).
    Verifies the request signature using X-Hub-Signature-256.
    """
    # Read request body for signature verification
    body = await request.body()
    
    # Get seller's WhatsApp credentials
    db = get_firestore_client()
    channel = get_user_channel(db, seller_id, "whatsapp")
    
    if not channel or not channel.get("credentials"):
        logger.warning(f"Webhook received for unconfigured seller: {seller_id}")
        return {"status": "error", "message": "Channel not configured"}
    
    # Verify webhook signature
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_service.verify_webhook_signature(body, signature_header, channel["credentials"]):
        logger.warning(f"Invalid webhook signature for seller: {seller_id}")
        raise HTTPException(status_code=403, detail="Invalid signature")
    
    # Parse webhook payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Process the webhook
    try:
        await _process_whatsapp_webhook(seller_id, payload, channel)
    except Exception as e:
        logger.error(f"Error processing WhatsApp webhook: {e}")
        # Return 200 to Meta to prevent retries, but log the error
        return {"status": "error", "message": str(e)}
    
    return {"status": "ok"}


async def _process_whatsapp_webhook(
    seller_id: str,
    payload: dict,
    channel: dict
):
    """Process incoming WhatsApp webhook payload."""
    entry = payload.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    
    messages = value.get("messages", [])
    statuses = value.get("statuses", [])
    
    # Handle incoming messages
    for msg in messages:
        await _handle_incoming_whatsapp_message(seller_id, msg, channel)
    
    # Handle message status updates (delivered, read, etc.)
    for status in statuses:
        await _handle_whatsapp_status_update(seller_id, status, channel)


async def _handle_incoming_whatsapp_message(
    seller_id: str,
    message: dict,
    channel: dict
):
    """Handle a single incoming WhatsApp message."""
    from app.agent import agent
    
    phone = message.get("from", "")
    message_id = message.get("id", "")
    message_type = message.get("type", "text")
    timestamp = message.get("timestamp", str(int(__import__("time").time())))
    
    # Extract text content
    if message_type == "text":
        text = message.get("text", {}).get("body", "")
    elif message_type == "image":
        text = "[Image received]"
    elif message_type == "document":
        text = "[Document received]"
    elif message_type == "audio":
        text = "[Audio message]"
    else:
        text = f"[{message_type.title()} message]"
    
    if not text:
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
    now = __import__("time").time()
    try:
        import zoneinfo
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
                "id": int((__import__("time").time()) * 1000),
                "sender": "ai",
                "content": ai_response.response,
                "time": time_str,
            }
            
            messages.append(ai_message)
            conv_ref.update({
                "messages": messages,
                "lastMessage": ai_response.response,
                "time": time_str,
                "updatedAt": __import__("time").time(),
            })
            
            # Send AI response back via WhatsApp
            await _send_whatsapp_reply(seller_id, phone, ai_response.response, channel)
            
        except Exception as e:
            logger.error(f"AI response generation failed: {e}")
            # Send fallback message
            fallback = "I'm having trouble processing your request. Please try again later."
            await _send_whatsapp_reply(seller_id, phone, fallback, channel)


async def _send_whatsapp_reply(
    seller_id: str,
    phone: str,
    message: str,
    channel: dict
):
    """Send a reply message via WhatsApp."""
    credentials = channel.get("credentials")
    if not credentials:
        logger.error(f"No WhatsApp credentials for seller: {seller_id}")
        return
    
    try:
        await whatsapp_service.send_text_message(credentials, phone, message)
    except ValueError as e:
        # Token expired or invalid
        logger.error(f"WhatsApp send failed (token issue): {e}")
        # Mark channel as disconnected
        db = get_firestore_client()
        upsert_user_channel(db, seller_id, "whatsapp", {
            "status": ChannelConnectionStatus.DISCONNECTED.value,
            "metadata": {
                **(channel.get("metadata") or {}),
                "lastError": str(e),
                "errorAt": __import__("time").time(),
            },
        })
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")


def _find_or_create_customer_by_phone(db, seller_id: str, phone: str) -> dict:
    """Find or create a customer by phone number."""
    customers_ref = db.collection("users").document(seller_id).collection("customers")
    
    # Search by phone
    query = customers_ref.where("phone", "==", phone)
    docs = list(query.stream())
    
    if docs:
        data = docs[0].to_dict()
        data["id"] = docs[0].id
        return data
    
    # Create new customer
    now = __import__("time").time()
    name = f"Customer {phone[-4:]}" if len(phone) >= 4 else f"Customer {phone}"
    initials = phone[-2:].upper() if len(phone) >= 2 else "CU"
    
    customer_data = {
        "name": name,
        "initials": initials,
        "phone": phone,
        "email": "",
        "location": "",
        "status": "New",
        "channel": "WhatsApp",
        "orders": 0,
        "totalSpent": 0.0,
        "conversations": 0,
        "lastInteraction": "",
        "joined": datetime.now().strftime("%B %d, %Y"),
        "notes": "",
        "products": [],
        "ordersList": [],
        "conversationsList": [],
        "online": False,
        "createdAt": now,
        "updatedAt": now,
    }
    
    doc_ref = customers_ref.document()
    doc_ref.set(customer_data)
    customer_data["id"] = doc_ref.id
    return customer_data


def _find_or_create_conversation(
    db, seller_id: str, customer: dict, channel: str, phone: str
) -> dict:
    """Find or create a conversation for a customer on a channel."""
    convs_ref = db.collection("users").document(seller_id).collection("conversations")
    
    # Search for existing open conversation with this customer
    query = convs_ref.where("channel", "==", channel)
    docs = list(query.stream())
    
    for doc in docs:
        data = doc.to_dict()
        if data.get("phone") == phone and data.get("conversationStatus") in ("open", "handed_off"):
            data["id"] = doc.id
            return data
    
    # Create new conversation
    now = __import__("time").time()
    conv_data = {
        "name": customer.get("name", f"Customer {phone[-4:]}"),
        "initials": customer.get("initials", "CU"),
        "status": "online",
        "channel": channel,
        "phone": phone,
        "email": customer.get("email", ""),
        "location": customer.get("location", ""),
        "lastMessage": "",
        "time": "now",
        "unread": 0,
        "mode": "ai",
        "conversationStatus": "open",
        "orders": [],
        "productsDiscussed": [],
        "messages": [],
        "createdAt": now,
        "updatedAt": now,
    }
    
    doc_ref = convs_ref.document()
    doc_ref.set(conv_data)
    conv_data["id"] = doc_ref.id
    return conv_data


async def _handle_whatsapp_status_update(
    seller_id: str,
    status: dict,
    channel: dict
):
    """Handle WhatsApp message status updates (delivered, read, etc.)."""
    # Status updates are logged but not processed further at this time
    message_id = status.get("id", "")
    status_type = status.get("status", "")
    logger.debug(f"WhatsApp status update for {seller_id}: {message_id} -> {status_type}")


# ============================================================
# CUSTOMERS
# ============================================================

@router.get("/customers", response_model=List[CustomerBase])
async def list_customers(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500)
):
    """List all customers for the current user's business."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    customers_ref = db.collection("users").document(user_id).collection("customers")
    query = customers_ref.order_by("updatedAt", direction="DESCENDING").limit(limit)
    
    if status:
        query = query.where("status", "==", status)
    
    docs = query.stream()
    customers = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        customers.append(CustomerBase(**data))
    
    return customers


@router.get("/customers/{customer_id}", response_model=CustomerBase)
async def get_customer(
    customer_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a single customer with full details."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    
    doc_ref = db.collection("users").document(user_id).collection("customers").document(customer_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    data = doc.to_dict()
    data["id"] = doc.id
    return CustomerBase(**data)


@router.post("/customers", response_model=CustomerBase)
async def create_customer(
    customer: CustomerCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new customer. Enforces collect phone/email settings."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageCustomers"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    # Enforce collect phone/email settings
    customer_settings = get_user_customer_settings(db, user_id)
    if customer_settings.get("collectPhone", True):
        if not customer.phone or customer.phone.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Phone number is required. Enable 'Collect phone number' in settings or provide a phone number."
            )
    if customer_settings.get("collectEmail", False):
        if not customer.email or customer.email.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Email address is required. Enable 'Collect email' in settings or provide an email address."
            )
    
    now = time.time()
    data = customer.model_dump()
    # Generate initials from name if not provided
    if not data.get("initials"):
        name_parts = data["name"].split()
        data["initials"] = "".join([p[0] for p in name_parts[:2]]).upper()
    
    general = _get_seller_general(db, user_id)
    timezone = general.get("timezone", "Africa/Accra")
    # Use timezone-aware date for joined (full month name)
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone)
        joined_str = datetime.now(tz).strftime("%B %d, %Y")
    except Exception:
        joined_str = datetime.now().strftime("%B %d, %Y")
    data.update({
        "orders": 0,
        "totalSpent": 0.0,
        "conversations": 0,
        "lastInteraction": "",
        "joined": joined_str,
        "products": [],
        "ordersList": [],
        "conversationsList": [],
        "createdAt": now,
        "updatedAt": now,
    })
    
    doc_ref = db.collection("users").document(user_id).collection("customers").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    
    return CustomerBase(**data)


@router.patch("/customers/{customer_id}", response_model=CustomerBase)
async def update_customer(
    customer_id: str,
    update: CustomerUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update customer details."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageCustomers"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("customers").document(customer_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    update_data = update.model_dump(exclude_unset=True)
    update_data["updatedAt"] = time.time()
    doc_ref.update(update_data)
    
    updated_doc = doc_ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id
    return CustomerBase(**data)


@router.delete("/customers/{customer_id}")
async def delete_customer(
    customer_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a customer."""
    db = get_firestore_client()
    user_id = current_user["uid"]
    if not check_team_permission(db, user_id, current_user["uid"], "canManageCustomers"):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    
    doc_ref = db.collection("users").document(user_id).collection("customers").document(customer_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    doc_ref.delete()
    return {"message": "Customer deleted"}