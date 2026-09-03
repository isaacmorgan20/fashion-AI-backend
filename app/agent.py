import json
import re
from typing import List, Dict, Any, Optional
from app.config import get_settings
from app.models import ProductBase, MessageBase, SenderType, AIResponse, ChatRequest


class ThreadOSAgent:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        if self.settings.google_ai_api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.settings.google_ai_api_key)
            except ImportError:
                # Fallback to deprecated package
                import google.generativeai as genai
                genai.configure(api_key=self.settings.google_ai_api_key)
                self.model = genai.GenerativeModel(self.settings.ai_model)
        else:
            self.model = None

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
            # Respect showAvailability setting - hide stock info if OFF
            show_availability = ai_settings.get("showAvailability", True)
            if show_availability:
                products_text = "\n".join([
                    f"- {p.name} ({p.category}): {currency} {p.price}, Stock: {p.stock}, Sizes: {', '.join(p.sizes) if p.sizes else 'N/A'}, Colors: {', '.join(p.colors) if p.colors else 'N/A'}"
                    for p in products
                ]) if products else "(No products in catalog)"
            else:
                products_text = "\n".join([
                    f"- {p.name} ({p.category}): {currency} {p.price}, Sizes: {', '.join(p.sizes) if p.sizes else 'N/A'}, Colors: {', '.join(p.colors) if p.colors else 'N/A'}"
                    for p in products
                ]) if products else "(No products in catalog)"

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
                # Use new google.genai client
                response = self.client.models.generate_content(
                    model=self.settings.ai_model,
                    contents=full_prompt,
                    config={
                        "temperature": self.settings.ai_temperature,
                        "max_output_tokens": self.settings.ai_max_tokens,
                    }
                )
                response_text = response.text
            else:
                # Fallback to deprecated package
                response = self.model.generate_content(
                    full_prompt,
                    generation_config={
                        "temperature": self.settings.ai_temperature,
                        "max_output_tokens": self.settings.ai_max_tokens,
                    }
                )
                response_text = response.text
            ai_resp = self._parse_ai_response(response_text)
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
            # Respect Human handoff OFF even on error
            if ai_settings.get("humanHandoff") is False:
                return AIResponse(
                    response="I'm having trouble processing your request. Please try again later.",
                    intent="error",
                    confidence=0.0,
                    requiresHandoff=False,
                    handoffReason=None
                )
            return AIResponse(
                response="I'm having trouble processing your request. Let me connect you with a human agent.",
                intent="error",
                confidence=0.0,
                requiresHandoff=True,
                handoffReason=f"AI error: {str(e)}"
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