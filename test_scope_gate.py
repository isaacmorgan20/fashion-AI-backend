import asyncio
from app.agent import agent, classify_scope
from app.models import ChatRequest, MessageBase, SenderType, ProductBase

products = [
    ProductBase(name='Black Evening Dress', category='Dresses', price=450, stock=12, sizes=['S','M','L'], colors=['Black'], description='Elegant dress', image='https://example.com/img.jpg'),
    ProductBase(name='Red Summer Dress', category='Dresses', price=380, stock=7, sizes=['S','M','L'], colors=['Red'], description='Summer dress', image='https://example.com/img2.jpg'),
]

business_info = {'businessName': 'ThreadOS Fashion', 'currency': 'GHS'}
ai_settings = {'enabled': True, 'autoReply': True, 'productRecommendations': True, 'customerMemory': True, 'humanHandoff': True, 'orderAssistance': True, 'responseStyle': 'Professional', 'confidenceThreshold': 'Medium'}

# Test scope classification directly
test_messages = [
    ('What dresses do you have?', True, 'product'),
    ('Price of Black Evening Dress', True, 'product'),
    ('Hello!', True, 'greeting'),
    ('Hi there', True, 'greeting'),
    ('What is the capital of France?', False, 'out_of_scope'),
    ('Who won the election?', False, 'out_of_scope:politics'),
    ('Football scores', False, 'out_of_scope:sports'),
    ('How to treat a headache?', False, 'out_of_scope:medical'),
    ('Python programming help', False, 'out_of_scope:technical'),
    ('Do you have Unicorn Dress?', True, 'product'),
    ('What is your return policy?', True, 'policy'),
    ('Track my order', True, 'order'),
    ('Contact info', True, 'business'),
    ('Gift for wedding', True, 'fashion_help'),
]

print('=== SCOPE CLASSIFICATION TESTS ===')
for msg, expected_in_scope, expected_reason in test_messages:
    is_in_scope, reason = classify_scope(msg)
    status = 'PASS' if is_in_scope == expected_in_scope else 'FAIL'
    print(f'{status} "{msg}" -> in_scope={is_in_scope} (reason: {reason})')

# Test full agent responses
async def test_agent():
    print('\n=== AGENT RESPONSE TESTS ===')
    
    # 1. Real product question
    req = ChatRequest(message='What dresses do you have?', conversationId='t1', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'1. Product Q: intent={r.intent}, products={r.productsMentioned}, response={r.response[:80]}...')
    
    # 2. Price/stock question
    req = ChatRequest(message='Price of Black Evening Dress', conversationId='t2', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'2. Price Q: intent={r.intent}, products={r.productsMentioned}, response={r.response[:80]}...')
    
    # 3. Business info
    req = ChatRequest(message='What is your phone number?', conversationId='t3', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'3. Business: intent={r.intent}, response={r.response[:80]}...')
    
    # 4. Greeting
    req = ChatRequest(message='Hello!', conversationId='t4', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'4. Greeting: intent={r.intent}, response={r.response[:80]}...')
    
    # 5. Unrelated general question
    req = ChatRequest(message='What is the capital of France?', conversationId='t5', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'5. Unrelated: intent={r.intent}, response={r.response[:80]}...')
    
    # 6. Politics
    req = ChatRequest(message='Who won the election?', conversationId='t6', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'6. Politics: intent={r.intent}, response={r.response[:80]}...')
    
    # 7. Unknown product (RAG test)
    req = ChatRequest(message='Do you have Unicorn Dress?', conversationId='t7', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'7. Unknown product: intent={r.intent}, products={r.productsMentioned}, response={r.response[:80]}...')
    
    # 8. Product recommendation
    req = ChatRequest(message='Recommend a dress for a wedding', conversationId='t8', conversationHistory=[])
    r = await agent.generate_response(req, products, business_info, ai_settings, {})
    print(f'8. Recommendation: intent={r.intent}, products={r.productsMentioned}, response={r.response[:80]}...')
    
    # 9. Response styles
    print('\n=== RESPONSE STYLE TESTS ===')
    for style in ['Professional', 'Friendly', 'Casual', 'Concise']:
        style_settings = {**ai_settings, 'responseStyle': style}
        req = ChatRequest(message='Hello, what do you sell?', conversationId=f't_{style}', conversationHistory=[])
        r = await agent.generate_response(req, products, business_info, style_settings, {})
        print(f'9.{style}: intent={r.intent}, response={r.response[:80]}...')
    
    # 10. Confidence thresholds
    print('\n=== CONFIDENCE THRESHOLD TESTS ===')
    for threshold in ['Low', 'Medium', 'High']:
        thresh_settings = {**ai_settings, 'confidenceThreshold': threshold}
        req = ChatRequest(message='asldkfj asldkfj', conversationId=f't_{threshold}', conversationHistory=[])
        r = await agent.generate_response(req, products, business_info, thresh_settings, {})
        print(f'10.{threshold}: confidence={r.confidence}, handoff={r.requiresHandoff}, intent={r.intent}')

asyncio.run(test_agent())