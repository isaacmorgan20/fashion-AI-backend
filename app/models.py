from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    WHATSAPP = "WhatsApp"
    INSTAGRAM = "Instagram"
    FACEBOOK = "Facebook"
    WEBSITE = "Website"


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