from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    WHATSAPP = "WhatsApp"
    INSTAGRAM = "Instagram"
    FACEBOOK = "Facebook"
    WEBSITE = "Website"
    TELEGRAM = "Telegram"


class ChannelType(str, Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    WEBSITE = "website"
    TELEGRAM = "telegram"


class ChannelConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    NOT_CONFIGURED = "not_configured"


class ChannelConnection(BaseModel):
    id: Optional[str] = None
    type: ChannelType
    status: ChannelConnectionStatus = ChannelConnectionStatus.NOT_CONFIGURED
    enabled: bool = False
    displayName: str = ""
    credentials: Optional[dict] = None
    metadata: Optional[dict] = None
    lastConnectedAt: Optional[float] = None
    lastMessageAt: Optional[float] = None
    createdAt: float = Field(default_factory=lambda: __import__("time").time())
    updatedAt: float = Field(default_factory=lambda: __import__("time").time())


class ChannelConnectionCreate(BaseModel):
    type: ChannelType
    enabled: bool = True
    credentials: Optional[dict] = None
    metadata: Optional[dict] = None


class ChannelConnectionUpdate(BaseModel):
    enabled: Optional[bool] = None
    credentials: Optional[dict] = None
    metadata: Optional[dict] = None


class ConversationMode(str, Enum):
    AI = "ai"
    HUMAN = "human"
    HANDOFF = "handoff"


class ConversationStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    HANDED_OFF = "handed_off"


class SenderType(str, Enum):
    CUSTOMER = "customer"
    AI = "ai"
    HUMAN = "human"


class CustomerStatus(str, Enum):
    NEW = "New"
    ACTIVE = "Active"
    REPEAT = "Repeat"
    VIP = "VIP"
    AT_RISK = "At Risk"


class CustomerBase(BaseModel):
    id: Optional[str] = None
    name: str
    initials: str
    phone: str = ""
    email: str = ""
    location: str = ""
    status: CustomerStatus = CustomerStatus.NEW
    channel: Channel = Channel.WEBSITE
    orders: int = 0
    totalSpent: float = 0.0
    conversations: int = 0
    lastInteraction: str = ""
    joined: str = Field(default_factory=lambda: datetime.now().strftime("%B %d, %Y"))
    notes: str = ""
    products: List[dict] = []
    ordersList: List[dict] = []
    conversationsList: List[dict] = []
    online: bool = False


class CustomerCreate(BaseModel):
    name: str
    initials: str
    phone: str = ""
    email: str = ""
    location: str = ""
    channel: Channel = Channel.WEBSITE
    notes: str = ""


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    status: Optional[CustomerStatus] = None
    notes: Optional[str] = None


class ProductBase(BaseModel):
    id: Optional[str] = None
    name: str
    category: str
    price: float
    stock: int
    sizes: List[str] = []
    colors: List[str] = []
    description: str = ""
    image: Optional[str] = None
    status: str = "In stock"


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    sizes: Optional[List[str]] = None
    colors: Optional[List[str]] = None
    description: Optional[str] = None
    image: Optional[str] = None
    status: Optional[str] = None


class OrderStatus(str, Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class OrderBase(BaseModel):
    id: Optional[str] = None
    customerId: Optional[str] = None
    customerName: str = ""
    productId: Optional[str] = None
    productName: str = ""
    product: str = ""  # alias for UI compat (same as productName)
    amount: str = ""  # e.g. "GHS 450"
    price: float = 0.0
    quantity: int = 1
    status: str = "Pending"
    date: str = Field(default_factory=lambda: datetime.now().strftime("%b %d, %Y"))
    createdAt: float = Field(default_factory=lambda: __import__("time").time())
    updatedAt: float = Field(default_factory=lambda: __import__("time").time())


class OrderCreate(BaseModel):
    customerId: Optional[str] = None
    customerName: str = ""
    productId: Optional[str] = None
    productName: str = ""
    product: Optional[str] = None
    price: float = 0.0
    amount: Optional[str] = None
    quantity: int = 1
    status: str = "Pending"


class OrderUpdate(BaseModel):
    customerName: Optional[str] = None
    productName: Optional[str] = None
    product: Optional[str] = None
    price: Optional[float] = None
    amount: Optional[str] = None
    quantity: Optional[int] = None
    status: Optional[str] = None


class MessageBase(BaseModel):
    id: Optional[int] = None
    sender: SenderType
    content: str
    time: str = Field(default_factory=lambda: datetime.now().strftime("%I:%M %p"))


class MessageCreate(BaseModel):
    content: str


class ConversationBase(BaseModel):
    id: Optional[str] = None
    name: str
    initials: str
    status: str = "online"
    channel: Channel
    lastMessage: str = ""
    time: str = "now"
    unread: int = 0
    mode: ConversationMode = ConversationMode.AI
    conversationStatus: ConversationStatus = ConversationStatus.OPEN
    phone: str = ""
    email: str = ""
    location: str = ""
    orders: List[dict] = []
    productsDiscussed: List[str] = []
    messages: List[MessageBase] = []

    @field_validator("channel", mode="before")
    @classmethod
    def normalize_channel(cls, v):
        """Normalize channel value to match Channel enum (case-insensitive)."""
        if isinstance(v, str):
            mapping = {
                "whatsapp": "WhatsApp",
                "instagram": "Instagram",
                "facebook": "Facebook",
                "website": "Website",
                "telegram": "Telegram",
            }
            return mapping.get(v.lower(), v)
        return v


class ConversationCreate(BaseModel):
    name: str
    initials: str
    channel: Channel
    phone: str = ""
    email: str = ""
    location: str = ""


class ConversationUpdate(BaseModel):
    mode: Optional[ConversationMode] = None
    conversationStatus: Optional[ConversationStatus] = None
    lastMessage: Optional[str] = None
    time: Optional[str] = None
    unread: Optional[int] = None


class AIResponse(BaseModel):
    response: str
    intent: str
    confidence: float
    suggestedActions: List[str] = []
    productsMentioned: List[str] = []
    requiresHandoff: bool = False
    handoffReason: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    conversationId: str
    conversationHistory: List[MessageBase] = []


class ChatResponse(BaseModel):
    response: str
    intent: str
    confidence: float
    suggestedActions: List[str] = []
    productsMentioned: List[str] = []
    requiresHandoff: bool = False
    handoffReason: Optional[str] = None


class AnalyticsResponse(BaseModel):
    conversations: int
    conversationsChange: float
    aiResolved: int
    aiResolvedChange: float
    responseTime: int
    responseTimeChange: float
    revenue: float
    revenueChange: float
    conversationChart: List[int]
    intents: List[dict]
    topProducts: List[dict]
    channels: List[dict]
    handoffs: int
    handoffReasons: List[dict]
    knowledgeGaps: List[dict]
    funnel: dict
    customers: dict


class SettingsBase(BaseModel):
    general: Optional[dict] = None
    ai: Optional[dict] = None
    customer: Optional[dict] = None
    notifications: Optional[dict] = None
    channels: Optional[dict] = None
    storefront: Optional[dict] = None
    knowledge: Optional[dict] = None
    team: Optional[List[dict]] = None
    security: Optional[dict] = None
    appearance: Optional[dict] = None
    updatedAt: Optional[float] = None


class SettingsUpdate(BaseModel):
    general: Optional[dict] = None
    ai: Optional[dict] = None
    customer: Optional[dict] = None
    notifications: Optional[dict] = None
    channels: Optional[dict] = None
    storefront: Optional[dict] = None
    knowledge: Optional[dict] = None
    team: Optional[List[dict]] = None
    security: Optional[dict] = None
    appearance: Optional[dict] = None


class NotificationEventType(str, Enum):
    NEW_CONVERSATION = "new_conversation"
    HUMAN_HANDOFF = "human_handoff"
    NEW_ORDER = "new_order"
    LOW_STOCK = "low_stock"
    DAILY_SUMMARY = "daily_summary"


class NotificationEvent(BaseModel):
    id: Optional[str] = None
    type: NotificationEventType
    title: str
    message: str
    metadata: Optional[dict] = None
    read: bool = False
    createdAt: float = Field(default_factory=lambda: __import__("time").time())


class NotificationEventCreate(BaseModel):
    type: NotificationEventType
    title: str
    message: str
    metadata: Optional[dict] = None


class StorefrontSettings(BaseModel):
    enabled: bool = True
    storeName: str = ""
    storeDescription: str = "Discover quality fashion, dresses, shoes and accessories."
    showPrices: bool = True
    showStock: bool = True
    showCustomerChat: bool = True
    showAiAssistant: bool = True
    allowOrdering: bool = True
    allowGuestBrowsing: bool = True


class PublicStorefront(BaseModel):
    sellerId: str
    storeName: str
    storeDescription: str
    showPrices: bool
    showStock: bool
    showCustomerChat: bool
    showAiAssistant: bool
    allowOrdering: bool
    allowGuestBrowsing: bool


class TeamMemberRole(str, Enum):
    OWNER = "Owner"
    ADMIN = "Admin"
    AGENT = "Agent"
    VIEWER = "Viewer"


class TeamMemberStatus(str, Enum):
    ACTIVE = "Active"
    PENDING = "Pending"
    INACTIVE = "Inactive"


class TeamMemberPermissions(BaseModel):
    canManageProducts: bool = False
    canManageOrders: bool = False
    canManageCustomers: bool = False
    canManageConversations: bool = False
    canManageSettings: bool = False
    canManageTeam: bool = False
    canViewAnalytics: bool = False


class TeamMember(BaseModel):
    id: str
    uid: Optional[str] = None
    name: str
    email: str
    role: TeamMemberRole = TeamMemberRole.AGENT
    status: TeamMemberStatus = TeamMemberStatus.PENDING
    permissions: TeamMemberPermissions = TeamMemberPermissions()
    invitedAt: Optional[float] = None
    joinedAt: Optional[float] = None
    invitedBy: Optional[str] = None


class TeamMemberCreate(BaseModel):
    email: str
    name: str
    role: TeamMemberRole = TeamMemberRole.AGENT
    permissions: Optional[TeamMemberPermissions] = None


class TeamMemberUpdate(BaseModel):
    role: Optional[TeamMemberRole] = None
    permissions: Optional[TeamMemberPermissions] = None
    status: Optional[TeamMemberStatus] = None


class Session(BaseModel):
    id: str
    user_id: str
    session_token_hash: str
    created_at: float
    last_active_at: float
    expires_at: float
    revoked_at: Optional[float] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    device_info: Optional[str] = None
    is_current: bool = False


class SessionCreate(BaseModel):
    user_id: str
    session_token_hash: str
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    device_info: Optional[str] = None
    timeout_minutes: int = 30


class SessionTimeout(str, Enum):
    FIFTEEN_MINUTES = "15 minutes"
    THIRTY_MINUTES = "30 minutes"
    ONE_HOUR = "1 hour"
    FOUR_HOURS = "4 hours"
    NEVER = "never"


TIMEOUT_MINUTES = {
    "15 minutes": 15,
    "30 minutes": 30,
    "1 hour": 60,
    "4 hours": 240,
    "never": 0,
}


class SecuritySettings(BaseModel):
    sessionTimeout: str = "30 minutes"
    requirePasswordChange: bool = False
    twoFactorEnabled: bool = False
    loginNotifications: bool = True
    sessionExpiry: bool = True