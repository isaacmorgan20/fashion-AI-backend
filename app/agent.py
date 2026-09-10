import json
import logging
import re
import asyncio
import os
from typing import List, Dict, Any, Optional, Callable, TypeVar
from app.config import get_settings
from app.models import ProductBase, MessageBase, SenderType, AIResponse, ChatRequest

logger = logging.getLogger(__name__)

T = TypeVar('T')


def _extract_status_code(e: Exception) -> Optional[int]:
    """
    Extract HTTP status code from Groq or httpx exceptions.
    """
    # Check for httpx response
    response = getattr(e, "response", None)
    if response is not None:
        for attr in ("status_code", "status", "code"):
            val = getattr(response, attr, None)
            if isinstance(val, int):
                return val
    
    # Check for Groq SDK error attributes
    for attr in ("code", "status_code", "status", "http_status"):
        val = getattr(e, attr, None)
        if isinstance(val, int):
            return val
    
    # Fallback: check error message for HTTP status pattern
    error_str = str(e)
    match = re.search(r'\b(4\d{2}|5\d{2})\b', error_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    return None


def _is_rate_limit_error(e: Exception) -> bool:
    """
    Determine if an exception represents a genuine rate limit (HTTP 429).
    """
    status = _extract_status_code(e)
    if status == 429:
        return True
    
    # Fallback string matching ONLY for 429 when SDK doesn't expose status
    error_str = str(e).lower()
    return "429" in error_str


def _is_auth_error(e: Exception) -> bool:
    """Check if exception is an authentication/authorization error (401, 403)."""
    status = _extract_status_code(e)
    if status in (401, 403):
        return True
    error_str = str(e).lower()
    return any(kw in error_str for kw in ("api key", "unauthorized", "forbidden", "invalid credential", "permission denied"))


def _is_model_error(e: Exception) -> bool:
    """Check if exception is a model-not-found/unavailable error (404, model-specific)."""
    status = _extract_status_code(e)
    if status == 404:
        return True
    error_str = str(e).lower()
    return any(kw in error_str for kw in ("model not found", "model unavailable", "model does not exist", "not found"))


def _is_network_timeout_error(e: Exception) -> bool:
    """Check if exception is a network/timeout error."""
    error_str = str(e).lower()
    network_keywords = ("timeout", "connection", "connect", "network", "dns", "unreachable", "timed out")
    return any(kw in error_str for kw in network_keywords) and "429" not in error_str


# ============================================================
# SCOPE GATE - Strict ThreadOS Fashion domain classification
# ============================================================

# Keywords that indicate IN-SCOPE topics
IN_SCOPE_KEYWORDS = {
    # Greetings & conversation
    "greeting": ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy", "greetings"),
    
    # Products & catalog
    "product": ("product", "dress", "shirt", "shoe", "shoes", "heel", "heels", "bag", "bags", "accessory", "accessories",
                "cloth", "clothes", "clothing", "wear", "outfit", "fashion", "style", "item", "items",
                "price", "cost", "how much", "ghs", "ghc", "cedi", "cedis",
                "size", "sizes", "small", "medium", "large", "xl", "xxl", "xs", "m ", " l ", " s ",
                "color", "colour", "black", "red", "blue", "white", "gold", "silver", "brown", "cream", "pink", "green",
                "stock", "available", "availability", "in stock", "out of stock", "low stock",
                "recommend", "suggest", "what do you have", "what's available", "catalog", "collection",
                "dress", "dresses", "kaftan", "men", "women", "unisex"),
    
    # Orders & purchasing
    "order": ("order", "buy", "purchase", "checkout", "cart", "payment", "pay", "card", "mobile money", "momo",
              "deliver", "delivery", "shipping", "ship", "courier", "track", "tracking", "where is my",
              "order status", "confirm", "confirmation", "receipt", "invoice"),
    
    # Policies & support
    "policy": ("return", "refund", "exchange", "policy", "warranty", "guarantee",
               "shipping", "cancel", "cancellation", "complaint", "issue", "problem", "wrong",
               "damaged", "defective", "quality"),
    
    # Business info
    "business": ("store", "shop", "business", "contact", "phone", "email", "location", "address",
                 "hours", "open", "close", "about us", "who are you", "threados"),
    
    # Fashion/shopping assistance
    "fashion_help": ("occasion", "wedding", "party", "event", "formal", "casual", "work", "office",
                     "outfit", "match", "go with", "wear with", "style", "styling", "trend",
                     "gift", "present", "birthday", "anniversary"),
    
    # Handoff
    "handoff": ("human", "agent", "person", "operator", "representative", "speak to someone", "talk to someone"),
}

# Keywords that strongly indicate OUT-OF-SCOPE topics
OUT_OF_SCOPE_KEYWORDS = {
    # Politics & news
    "politics": ("politic", "government", "election", "president", "minister", "parliament", "vote", "voting",
                 "policy ", "legislat", "congress", "senate", "democrat", "republican", "party", "campaign"),
    
    # News & current events
    "news": ("news", "headline", "breaking", "reporter", "journalist", "article", "press", "media"),
    
    # Sports
    "sports": ("football", "soccer", "basketball", "tennis", "cricket", "olympics", "world cup", "championship",
               "league", "match", "game", "score", "team", "player", "coach", "tournament"),
    
    # Education/academic
    "education": ("homework", "assignment", "exam", "test", "quiz", "study", "university", "college", "school",
                  "degree", "thesis", "research", "paper", "essay", "grade", "professor", "teacher", "lecture"),
    
    # Medical/health
    "medical": ("diagnos", "symptom", "disease", "illness", "medicine", "drug", "prescription", "doctor", "hospital",
                "treatment", "therapy", "health", "medical", "pain", "fever", "infection", "virus", "covid",
                "headache", "migraine", "treat", "cure", "heal", "remedy", "pill", "tablet", "clinic", "nurse",
                "pharmacy", "pharmacist", "allergy", "rash", "cough", "cold", "flu", "sick", "nausea", "vomit"),
    
    # Legal
    "legal": ("law", "legal", "court", "judge", "lawyer", "attorney", "sue", "lawsuit", "contract", "statute",
              "regulation", "compliance", "litigation", "rights", "patent", "copyright", "trademark"),
    
    # Financial advice (beyond simple payment)
    "financial_advice": ("invest", "investment", "stock market", "bond", "crypto", "bitcoin", "trading", "portfolio",
                         "interest rate", "mortgage", "loan", "credit score", "tax", "accounting", "audit"),
    
    # Technical/programming
    "technical": ("code", "program", "python", "javascript", "java", "api", "database", "sql", "server",
                  "deploy", "docker", "kubernetes", "aws", "azure", "git", "github", "bug", "debug", "compile"),
    
    # Other businesses/brands
    "other_brands": ("zara", "hm ", "nike", "adidas", "gucci", "prada", "louis vuitton", "chanel", "versace",
                     "amazon", "jumia", "aliexpress", "ebay", "shopify", "walmart", "target"),
    
    # Personal/private topics
    "personal": ("relationship", "dating", "marriage", "divorce", "boyfriend", "girlfriend", "husband", "wife",
                 "family", "parent", "child", "pregnan", "baby", "mental health", "therapy", "depression", "anxiety"),
    
    # Entertainment
    "entertainment": ("movie", "film", "actor", "actress", "celebrity", "netflix", "youtube", "music", "song",
                      "album", "concert", "festival", "tv show", "series", "game of thrones", "star wars"),
}

# Combined negative keywords for quick rejection
ALL_OUT_OF_SCOPE_KEYWORDS = set()
for cat_keywords in OUT_OF_SCOPE_KEYWORDS.values():
    ALL_OUT_OF_SCOPE_KEYWORDS.update(cat_keywords)


def classify_scope(message: str) -> tuple[bool, str]:
    """
    Classify if a message is IN_SCOPE for ThreadOS Fashion.
    
    Returns:
        (is_in_scope, reason)
        - is_in_scope: True if message is within ThreadOS Fashion scope
        - reason: description of why (e.g., "greeting", "product_inquiry", "out_of_scope:politics")
    """
    msg_lower = message.lower().strip()
    
    # Empty or very short messages - treat as greeting-ish
    if len(msg_lower) < 3:
        return True, "short_message"
    
    # Check for explicit OUT-OF-SCOPE keywords first (stronger signal)
    for category, keywords in OUT_OF_SCOPE_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                return False, f"out_of_scope:{category}"
    
    # Check for IN-SCOPE keywords
    for category, keywords in IN_SCOPE_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                return True, category
    
    # Check for question patterns that are likely shopping-related
    shopping_question_patterns = [
        r"\bwhat\s+(do\s+you\s+)?(have|sell|offer)\b",
        r"\bhow\s+(much|cost|price)\b",
        r"\bwhere\s+(can\s+i|to\s+)\b",
        r"\bcan\s+(i|you)\b.*\b(get|buy|find)\b",
        r"\bis\s+(this|that|it)\b.*\b(available|in\s+stock)\b",
        r"\bdo\s+you\s+(have|sell|carry)\b",
    ]
    import re
    for pattern in shopping_question_patterns:
        if re.search(pattern, msg_lower):
            return True, "shopping_question"
    
    # Default: if unclear, be conservative and allow (let AI handle with low confidence → handoff)
    # But for very obviously off-topic, we could reject. For now, allow with low confidence path.
    return True, "unclear_allow"


async def _retry_with_backoff(func: Callable[[], T], max_retries: int = 3, base_delay: float = 1.0) -> T:
    """Retry a function with exponential backoff for GENUINE rate limit errors only."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()
        except Exception as e:
            last_exception = e
            # Only retry on GENUINE rate limit (HTTP 429)
            if _is_rate_limit_error(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[AI AGENT] Rate limit (429) hit (attempt {attempt + 1}/{max_retries}), retrying in {delay}s")
                await asyncio.sleep(delay)
                continue
            # Not a rate limit error, or max retries reached - don't retry
            raise
    raise last_exception


class ThreadOSAgent:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        
        # Validate API key presence (never log the key itself)
        api_key = self.settings.groq_api_key
        if not api_key or not api_key.strip():
            logger.error("[AI AGENT] GROQ_API_KEY is not configured. AI service will be unavailable.")
        elif len(api_key.strip()) < 10:
            logger.error("[AI AGENT] GROQ_API_KEY appears invalid (too short). AI service will be unavailable.")
            api_key = None
        
        if api_key:
            # Use Groq client (OpenAI-compatible API)
            try:
                from groq import Groq
                self.client = Groq(api_key=api_key)
                logger.info(f"[AI AGENT] Initialized Groq client with model={self.settings.groq_model}")
            except ImportError:
                logger.error("[AI AGENT] Groq package not available. Please install 'groq>=1.7.0'")
            except Exception as e:
                logger.error(f"[AI AGENT] Failed to initialize Groq client: {type(e).__name__}: {e}")
        else:
            self.client = None

    async def _generate_with_retry(self, func: Callable[[], T]) -> T:
        """Generate content with retry logic for rate limits."""
        return await _retry_with_backoff(func, max_retries=3, base_delay=1.5)

    def _get_system_prompt(self, products: List[ProductBase], business_info: Dict[str, Any], ai_settings: Optional[Dict[str, Any]] = None, knowledge_settings: Optional[Dict[str, Any]] = None) -> str:
        ai_settings = ai_settings or {}
        knowledge_settings = knowledge_settings or {}
        
        # Use real product catalog as RAG source - never invent
        currency = business_info.get('currency', 'GHS')
        
        # Respect product information toggle
        if not knowledge_settings.get("productInformation", True):
            products_text = "(Product information disabled - do not reference products)"
        elif ai_settings.get("productRecommendations") is False:
            products_text = "(Product recommendations disabled - do not suggest products)"
        else:
            # Build a CONCISE product summary for the AI - not the full catalog dump
            # AI should answer naturally and only mention specific products when relevant
            if products:
                # Count by category for summary
                from collections import Counter
                cat_counts = Counter(p.category for p in products)
                cat_summary = ", ".join(f"{count} {cat}" for cat, count in cat_counts.items())
                
                # Price range
                prices = [p.price for p in products if p.price > 0]
                price_range = f"{currency} {min(prices):.0f}–{currency} {max(prices):.0f}" if prices else "N/A"
                
                products_text = f"""CATALOG SUMMARY (reference only - do not list unless asked):
- {len(products)} products across: {cat_summary}
- Price range: {price_range}
- Categories available: {', '.join(cat_counts.keys())}

FULL PRODUCT DETAILS (use ONLY when customer asks about a specific product):
"""
                # Add full details but mark as reference
                for p in products:
                    stock_info = f", Stock: {p.stock}" if ai_settings.get("showAvailability", True) else ""
                    products_text += f"- {p.name} ({p.category}): {currency} {p.price}{stock_info}, Sizes: {', '.join(p.sizes) if p.sizes else 'N/A'}, Colors: {', '.join(p.colors) if p.colors else 'N/A'}\n"
            else:
                products_text = "(No products in catalog)"

        # Response style
        style = ai_settings.get("responseStyle", "Professional")
        style_guidance = {
            "Professional": "Be helpful, professional, and conversational. Keep responses concise but complete.",
            "Friendly": "Be warm, friendly, and conversational. Use a welcoming tone and emojis sparingly.",
            "Casual": "Be casual, relaxed, and conversational. Use informal language.",
            "Concise": "Be brief and to the point. Keep responses short and direct.",
        }.get(style, "Be helpful, professional, and conversational.")

        # Order assistance
        order_capability = "3. Assist with placing orders" if ai_settings.get("orderAssistance", True) else "3. Order assistance is disabled - do not handle order/product assistance, hand off if needed"

        # Stock visibility
        stock_guideline = "" if ai_settings.get("showAvailability", True) else "- Do NOT mention stock levels, inventory counts, or whether items are in/out of stock. Simply state sizes and colors are available if asked."

        # Human handoff
        handoff_enabled = ai_settings.get("humanHandoff", True)
        handoff_section = """HANDOFF TRIGGERS:
- Customer explicitly requests human
- Complex issues (complaints, refunds, special requests)
- Low confidence in response
- Technical issues beyond your scope""" if handoff_enabled else "HANDOFF DISABLED: Do not offer or perform automatic human handoff. Handle within AI scope or state that human handoff is not available."

        # Build business info section based on businessInformation toggle
        business_section = ""
        if knowledge_settings.get("businessInformation", True):
            custom_business_info = knowledge_settings.get("businessInformationContent", "").strip()
            if custom_business_info:
                business_section = f"""BUSINESS INFORMATION:
{custom_business_info}"""
            else:
                business_section = f"""BUSINESS INFO:
- Name: {business_info.get('businessName', 'ThreadOS Fashion')}
- Category: {business_info.get('businessCategory', 'Fashion & Apparel')}
- Currency: {currency}
- Phone: {business_info.get('businessPhone', 'N/A')}
- Email: {business_info.get('businessEmail', 'N/A')}
- Location: Ghana
- Delivery: 1-2 business days within Ghana"""

        # Build FAQ section
        faq_section = ""
        if knowledge_settings.get("faq", True):
            faq_content = knowledge_settings.get("faqContent", "").strip()
            if faq_content:
                faq_section = f"""FAQ (answer customer questions using this):
{faq_content}"""

        # Build delivery policy section
        delivery_section = ""
        if knowledge_settings.get("deliveryPolicy", True):
            delivery_content = knowledge_settings.get("deliveryPolicyContent", "").strip()
            if delivery_content:
                delivery_section = f"""DELIVERY POLICY:
{delivery_content}"""
            else:
                delivery_section = "DELIVERY POLICY: Standard delivery within 1-2 business days in Ghana."

        # Build return policy section
        return_section = ""
        if knowledge_settings.get("returnPolicy", True):
            return_content = knowledge_settings.get("returnPolicyContent", "").strip()
            if return_content:
                return_section = f"""RETURN POLICY:
{return_content}"""

        # Build payment policy section
        payment_section = ""
        if knowledge_settings.get("paymentPolicy", True):
            payment_content = knowledge_settings.get("paymentPolicyContent", "").strip()
            if payment_content:
                payment_section = f"""PAYMENT POLICY:
{payment_content}"""

        # Build order information section
        order_section = ""
        if knowledge_settings.get("orderInformation", True):
            order_content = knowledge_settings.get("orderInformationContent", "").strip()
            if order_content:
                order_section = f"""ORDER INFORMATION:
{order_content}"""

        # Build policy section from enabled policies
        policy_parts = []
        if delivery_section:
            policy_parts.append(delivery_section)
        if return_section:
            policy_parts.append(return_section)
        if payment_section:
            policy_parts.append(payment_section)
        if order_section:
            policy_parts.append(order_section)
        
        policy_section = "\n\n".join(policy_parts) if policy_parts else ""

        return f"""You are ThreadOS AI, a customer service and commerce agent for {business_info.get('businessName', 'ThreadOS Fashion')}.

{business_section}

PRODUCT CATALOG (RAG source - use only this, never invent):
{products_text}

{faq_section}

{policy_section}

YOUR CAPABILITIES:
1. Answer product questions (availability, price, sizes, colors, details)
2. Help customers discover products based on preferences
{order_capability}
4. Answer policy questions (delivery, returns, payments)
5. Maintain conversation context
6. Detect when human handoff is needed

RESPONSE GUIDELINES:
- {style_guidance}
- Use the business currency ({currency})
- Reference real product data from the catalog - never make up product info not in the catalog
- If unsure about something, offer to connect to human
- Keep responses concise but complete
{stock_guideline}
- DO NOT use markdown formatting (no **bold**, *italic*, `code`, # headers, - bullet lists)
- DO NOT dump the full product catalog unless customer explicitly asks "show all products" or "list everything"
- When customer asks about a category (e.g., "what dresses do you have?"), mention ONLY relevant products naturally
- When recommending a specific product, include its name, price, and key details (colors/sizes) in plain text
- Write as a natural fashion store conversation, not a structured list

{handoff_section}

Return JSON with:
{{
  "response": "your response to customer",
  "intent": "product_inquiry|order_assistance|policy_question|greeting|handoff_request|other",
  "confidence": 0.95,
  "suggestedActions": ["action1", "action2"],
  "productsMentioned": ["product names"],
  "requiresHandoff": false,
  "handoffReason": null
}}"""

    def _parse_ai_response(self, response_text: str) -> AIResponse:
        """Parse AI response, handling both JSON and plain text."""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return AIResponse(**data)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: treat as plain text response
        return AIResponse(
            response=response_text.strip(),
            intent="other",
            confidence=0.5,
            suggestedActions=[],
            productsMentioned=[],
            requiresHandoff=False,
            handoffReason=None
        )

    def _extract_products_mentioned(self, text: str, products: List[ProductBase]) -> List[str]:
        """Extract product names mentioned in text."""
        mentioned = []
        text_lower = text.lower()
        for product in products:
            if product.name.lower() in text_lower:
                mentioned.append(product.name)
        return mentioned

    async def generate_response(
        self,
        request: ChatRequest,
        products: List[ProductBase],
        business_info: Dict[str, Any],
        ai_settings: Optional[Dict[str, Any]] = None,
        knowledge_settings: Optional[Dict[str, Any]] = None
    ) -> AIResponse:
        """Generate AI response for customer message."""
        ai_settings = ai_settings or {}
        knowledge_settings = knowledge_settings or {}
        if not self.client:
            # Respect Human handoff OFF even when AI not configured
            if ai_settings.get("humanHandoff") is False:
                return AIResponse(
                    response="I'm currently unavailable. Please try again later.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason=None
                )
            return AIResponse(
                response="I'm currently unavailable. Please try again later or contact our support team.",
                intent="error",
                confidence=0.0,
                requiresHandoff=True,
                handoffReason="AI service not configured"
            )
        # Respect Customer memory OFF → do not use previous interactions
        conversation_context = ""
        if ai_settings.get("customerMemory", True):
            for msg in request.conversationHistory[-6:]:
                sender_label = "Customer" if msg.sender == SenderType.CUSTOMER else "AI" if msg.sender == SenderType.AI else "Agent"
                conversation_context += f"{sender_label}: {msg.content}\n"
        else:
            conversation_context = "(Previous conversation history not available - customer memory disabled)\n"

        # SCOPE GATE: Check if message is within ThreadOS Fashion domain
        is_in_scope, scope_reason = classify_scope(request.message)
        if not is_in_scope:
            logger.info(f"[AI AGENT] OUT_OF_SCOPE detected: reason={scope_reason}, message={request.message[:100]}")
            # Return polite redirect without calling Groq
            redirect_responses = {
                "out_of_scope:politics": "I'm here to help with ThreadOS Fashion products, orders, and store support. For political topics, I'd recommend a news source.",
                "out_of_scope:news": "I specialize in fashion shopping assistance. For current events, please check a news website.",
                "out_of_scope:sports": "I can help you find the perfect outfit for game day! For sports scores and updates, try a sports app.",
                "out_of_scope:education": "I'm your fashion assistant, not a tutor. For homework help, try an educational resource.",
                "out_of_scope:medical": "I can't provide medical advice. Please consult a healthcare professional for health concerns.",
                "out_of_scope:legal": "I'm not qualified to give legal advice. Please speak with a lawyer for legal matters.",
                "out_of_scope:financial_advice": "I can help with fashion purchases and payments. For financial advice, consult a financial advisor.",
                "out_of_scope:technical": "I'm here for fashion shopping, not tech support. For programming help, try Stack Overflow or documentation.",
                "out_of_scope:other_brands": "I only have information about ThreadOS Fashion products. I can't compare or discuss other brands.",
                "out_of_scope:personal": "I'm here to help with your fashion shopping. For personal matters, I'd suggest speaking with appropriate professionals.",
                "out_of_scope:entertainment": "I can help you find something stylish to wear! For entertainment news, check entertainment websites.",
            }
            redirect_msg = redirect_responses.get(scope_reason, 
                "I'm here to help with ThreadOS Fashion products, orders, delivery, returns, and store information. How can I assist you with your shopping today?")
            return AIResponse(
                response=redirect_msg,
                intent="out_of_scope",
                confidence=0.0,
                suggestedActions=["Browse products", "Track order", "Store policies", "Contact support"],
                productsMentioned=[],
                requiresHandoff=False,
                handoffReason=None
            )

        prompt = self._get_system_prompt(products, business_info, ai_settings, knowledge_settings)
        full_prompt = f"{prompt}\n\nCONVERSATION HISTORY:\n{conversation_context}\nCustomer: {request.message}\n\nRespond as JSON:"

        try:
            if self.client:
                # Use Groq client (OpenAI-compatible API) with retry for rate limits
                logger.info(f"[AI AGENT] Calling Groq client with model={self.settings.groq_model}")
                response = await self._generate_with_retry(
                    lambda: self.client.chat.completions.create(
                        model=self.settings.groq_model,
                        messages=[{"role": "user", "content": full_prompt}],
                        temperature=self.settings.ai_temperature,
                        max_tokens=self.settings.ai_max_tokens,
                    )
                )
                response_text = response.choices[0].message.content
                logger.info(f"[AI AGENT] Groq response received, len={len(response_text)}")
                logger.debug(f"[AI AGENT] Response text preview: {response_text[:200]}")
            else:
                # AI client not initialized
                logger.error("[AI AGENT] Groq client not initialized")
                return AIResponse(
                    response="I'm currently unavailable. Please try again later or contact our support team.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=True,
                    handoffReason="AI service not configured"
                )
            logger.info(f"[AI AGENT] Parsing response...")
            ai_resp = self._parse_ai_response(response_text)
            logger.info(f"[AI AGENT] Parsed response: intent={ai_resp.intent}, confidence={ai_resp.confidence}, requires_handoff={ai_resp.requiresHandoff}, response_len={len(ai_resp.response)}")
            # Enforce AI settings - real business logic
            # Product recommendations OFF → strip product mentions
            if ai_settings.get("productRecommendations") is False:
                ai_resp.productsMentioned = []
                # If AI still recommended products in text, we keep text but don't highlight products
                # Ensure we use only catalog products (RAG) - filter out invented products
            # Filter productsMentioned to only real catalog products (RAG - never invent)
            if products:
                real_names = {p.name for p in products}
                ai_resp.productsMentioned = [p for p in ai_resp.productsMentioned if p in real_names]
                # Also verify response doesn't invent products not in catalog - if it does, clear it
                # (simple check: if response mentions a product not in catalog, we don't auto-correct text, but we ensure productsMentioned is accurate)
            # Order assistance OFF → hand off if intent is order
            if ai_settings.get("orderAssistance") is False and ai_resp.intent == "order_assistance":
                ai_resp.requiresHandoff = True
                ai_resp.handoffReason = "Order assistance is disabled for this business"
                ai_resp.response = "Order assistance is currently not available. Let me connect you with a human agent who can help with your order."
            # Human handoff OFF → never hand off automatically
            if ai_settings.get("humanHandoff") is False and ai_resp.requiresHandoff:
                ai_resp.requiresHandoff = False
                ai_resp.handoffReason = None
                # Provide alternative response without handoff
                if not ai_resp.response:
                    ai_resp.response = "I understand you need assistance. Our team will review your message and respond as soon as possible."
            # Confidence threshold → Low/Medium/High affects handoff
            threshold_map = {"Low": 0.3, "Medium": 0.6, "High": 0.8}
            thresh = threshold_map.get(ai_settings.get("confidenceThreshold", "Medium"), 0.6)
            if ai_resp.confidence < thresh and not ai_resp.requiresHandoff:
                # Only enforce if human handoff is enabled, otherwise just lower confidence
                if ai_settings.get("humanHandoff", True):
                    ai_resp.requiresHandoff = True
                    ai_resp.handoffReason = f"Low confidence ({ai_resp.confidence:.2f} < {thresh}) - confidence threshold {ai_settings.get('confidenceThreshold','Medium')}"
            return ai_resp
        except Exception as e:
            import traceback
            
            # Diagnostic logging - detailed error info for debugging
            # NEVER logs API keys, tokens, or secrets
            status_code = _extract_status_code(e)
            logger.error(
                f"[AI AGENT] Generation failed | "
                f"type={type(e).__name__} | "
                f"status={status_code} | "
                f"message={str(e)}"
            )
            logger.debug(f"[AI AGENT] Full traceback:\n{traceback.format_exc()}")
            
            # Classify error and respond appropriately
            # Priority order: Rate limit > Auth > Model > Network > Unknown
            
            if _is_rate_limit_error(e):
                # GENUINE rate limit (HTTP 429)
                logger.warning(f"[AI AGENT] Genuine rate limit detected (status={status_code})")
                return AIResponse(
                    response="I'm temporarily unable to process your request due to high demand. Please try again in a moment.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason="Rate limit exceeded"
                )
            
            if _is_auth_error(e):
                # Authentication/API key error - don't tell customer "high demand"
                logger.error(f"[AI AGENT] Authentication error (status={status_code}) - check GROQ_API_KEY")
                return AIResponse(
                    response="I'm having trouble connecting to the AI service. Please try again later.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason="Authentication error"
                )
            
            if _is_model_error(e):
                # Model not found/unavailable
                logger.error(f"[AI AGENT] Model error (status={status_code}) - model may be unavailable")
                return AIResponse(
                    response="I'm having trouble with the AI model. Please try again later.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason="Model error"
                )
            
            if _is_network_timeout_error(e):
                # Network/timeout error
                logger.warning(f"[AI AGENT] Network/timeout error: {str(e)}")
                return AIResponse(
                    response="I'm having trouble connecting to the AI service. Please try again in a moment.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason="Network error"
                )
            
            # Unknown error - log full details, use generic fallback
            logger.error(f"[AI AGENT] Unexpected error: {type(e).__name__}: {e}")
            return AIResponse(
                response="I'm having trouble processing your request. Let me connect you with a human agent.",
                intent="error",
                confidence=0.0,
                requiresHandoff=True,
                handoffReason=f"AI error: {type(e).__name__}"
            )

    def detect_intent_simple(self, message: str) -> Dict[str, Any]:
        """Simple rule-based intent detection as fallback."""
        message_lower = message.lower()

        # Handoff requests
        handoff_keywords = ["speak to someone", "talk to human", "human agent", "real person", "operator"]
        if any(kw in message_lower for kw in handoff_keywords):
            return {
                "intent": "handoff_request",
                "confidence": 0.9,
                "requiresHandoff": True,
                "handoffReason": "Customer requested human agent"
            }

        # Greeting
        greeting_keywords = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
        if any(kw in message_lower for kw in greeting_keywords) and len(message.split()) <= 3:
            return {
                "intent": "greeting",
                "confidence": 0.8,
                "requiresHandoff": False
            }

        # Product inquiry
        product_keywords = ["price", "cost", "how much", "available", "stock", "size", "color", "colour"]
        if any(kw in message_lower for kw in product_keywords):
            return {
                "intent": "product_inquiry",
                "confidence": 0.7,
                "requiresHandoff": False
            }

        # Order assistance
        order_keywords = ["order", "buy", "purchase", "checkout", "payment", "deliver", "delivery"]
        if any(kw in message_lower for kw in order_keywords):
            return {
                "intent": "order_assistance",
                "confidence": 0.7,
                "requiresHandoff": False
            }

        # Policy
        policy_keywords = ["return", "refund", "exchange", "policy", "warranty", "shipping", "shipping"]
        if any(kw in message_lower for kw in policy_keywords):
            return {
                "intent": "policy_question",
                "confidence": 0.7,
                "requiresHandoff": False
            }

        return {
            "intent": "other",
            "confidence": 0.5,
            "requiresHandoff": False
        }


# Singleton instance
agent = ThreadOSAgent()