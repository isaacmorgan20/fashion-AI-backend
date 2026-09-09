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
    Extract HTTP status code from google.genai or google.generativeai exceptions.
    
    The google.genai SDK (v1) raises exceptions with .code or .status attributes.
    The deprecated google.generativeai may include status in the error message.
    """
    # google.genai (new SDK) - exceptions often have .code or .status
    for attr in ("code", "status", "status_code", "http_status"):
        val = getattr(e, attr, None)
        if isinstance(val, int):
            return val
    
    # Check if exception has a response object with status
    response = getattr(e, "response", None)
    if response is not None:
        for attr in ("status_code", "status", "code"):
            val = getattr(response, attr, None)
            if isinstance(val, int):
                return val
    
    # Fallback: check error message for HTTP status pattern
    # This is a last resort - prefer SDK-provided status codes
    error_str = str(e)
    import re
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
    
    Prefers SDK-provided status codes over string matching to avoid false positives.
    """
    status = _extract_status_code(e)
    if status == 429:
        return True
    
    # Fallback string matching ONLY for 429 when SDK doesn't expose status
    # Do NOT match "quota", "exhausted", "limit" etc. without 429 status
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
    # Check for timeout, connection, network errors
    network_keywords = ("timeout", "connection", "connect", "network", "dns", "unreachable", "timed out")
    return any(kw in error_str for kw in network_keywords) and "429" not in error_str


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
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 1.5s, 3s, 6s
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
        self.model = None
        
        # Validate API key presence (never log the key itself)
        api_key = self.settings.google_ai_api_key
        if not api_key or not api_key.strip():
            logger.error("[AI AGENT] GOOGLE_AI_API_KEY is not configured. AI service will be unavailable.")
        elif len(api_key.strip()) < 10:
            logger.error("[AI AGENT] GOOGLE_AI_API_KEY appears invalid (too short). AI service will be unavailable.")
            api_key = None
        
        if api_key:
            # Use new google.genai package with v1 API (not v1beta)
            try:
                from google import genai
                self.client = genai.Client(
                    api_key=api_key,
                    http_options={"api_version": "v1"}
                )
                logger.info("[AI AGENT] Initialized google.genai client (v1 API)")
            except ImportError:
                # Fallback to deprecated google.generativeai package
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    self.model = genai.GenerativeModel(self.settings.ai_model)
                    logger.warning("[AI AGENT] Using deprecated google.generativeai package (fallback)")
                except ImportError:
                    logger.error("[AI AGENT] Neither google.genai nor google.generativeai available")
            except Exception as e:
                logger.error(f"[AI AGENT] Failed to initialize AI client: {type(e).__name__}")
        else:
            self.model = None

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
        if not self.client and not self.model:
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

        prompt = self._get_system_prompt(products, business_info, ai_settings, knowledge_settings)
        full_prompt = f"{prompt}\n\nCONVERSATION HISTORY:\n{conversation_context}\nCustomer: {request.message}\n\nRespond as JSON:"

        try:
            if self.client:
                # Use new google.genai client with retry for rate limits
                logger.info(f"[AI AGENT] Calling new google.genai client with model={self.settings.ai_model}")
                response = await self._generate_with_retry(
                    lambda: self.client.models.generate_content(
                        model=self.settings.ai_model,
                        contents=full_prompt,
                        config={
                            "temperature": self.settings.ai_temperature,
                            "max_output_tokens": self.settings.ai_max_tokens,
                        }
                    )
                )
                response_text = response.text
                logger.info(f"[AI AGENT] New client response received, len={len(response_text)}")
                logger.debug(f"[AI AGENT] Response text preview: {response_text[:200]}")
            else:
                # Fallback to deprecated package with retry
                logger.info(f"[AI AGENT] Calling deprecated google.generativeai with model={self.settings.ai_model}")
                response = await self._generate_with_retry(
                    lambda: self.model.generate_content(
                        full_prompt,
                        generation_config={
                            "temperature": self.settings.ai_temperature,
                            "max_output_tokens": self.settings.ai_max_tokens,
                        }
                    )
                )
                response_text = response.text
                logger.info(f"[AI AGENT] Deprecated package response received, len={len(response_text)}")
                logger.debug(f"[AI AGENT] Response text preview: {response_text[:200]}")
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
                logger.error(f"[AI AGENT] Authentication error (status={status_code}) - check GOOGLE_AI_API_KEY")
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