import requests, json, time
url='https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=AIzaSyBPvgPEN8916bKwMZlz1_NR487NFijAApo'
resp=requests.post(url, json={'email':'test@example.com','password':'testpassword123','returnSecureToken':True})
tok=resp.json().get('idToken')
h={'Authorization': f'Bearer {tok}'}

def get_ai():
    r=requests.get('http://127.0.0.1:8000/api/v1/settings', headers=h)
    return r.json().get('ai',{})

def set_ai(patch):
    r=requests.patch('http://127.0.0.1:8000/api/v1/settings', headers=h, json={'ai': patch})
    return r.json().get('ai')

def chat(msg, history=[]):
    # need a valid conversationId - use existing or create one
    # First get a conversation or create
    convs=requests.get('http://127.0.0.1:8000/api/v1/conversations', headers=h).json()
    if convs:
        cid=convs[0]['id']
    else:
        # create a dummy conversation
        cr=requests.post('http://127.0.0.1:8000/api/v1/conversations', headers=h, json={'name':'Test','initials':'TT','channel':'Website'})
        cid=cr.json().get('id')
    payload={'message':msg,'conversationId':cid,'conversationHistory':history}
    r=requests.post('http://127.0.0.1:8000/api/v1/chat', headers=h, json=payload)
    return r.json()

print("Initial AI settings:", get_ai())
# Test 1: Enable AI OFF
print("\n=== Test 1: Enable AI OFF ===")
orig=get_ai()
set_ai({"enabled": False})
r=chat("Hello, what is the price of Black Evening Dress?")
print("Response requiresHandoff:", r.get('requiresHandoff'), "handoffReason:", r.get('handoffReason'))
print("PASS" if r.get('requiresHandoff') and "disabled" in str(r.get('handoffReason')).lower() else "FAIL")
set_ai({"enabled": True})

# Test 2: Automatic replies OFF
print("\n=== Test 2: Automatic replies OFF ===")
set_ai({"autoReply": False})
r=chat("Hi")
print("requiresHandoff:", r.get('requiresHandoff'), "reason:", r.get('handoffReason'))
print("PASS" if r.get('requiresHandoff') else "FAIL")
set_ai({"autoReply": True})

# Test 3: Product recommendations OFF
print("\n=== Test 3: Product recommendations OFF ===")
set_ai({"productRecommendations": False})
r=chat("Can you recommend a dress for a wedding?")
print("productsMentioned:", r.get('productsMentioned'))
print("PASS" if not r.get('productsMentioned') else "FAIL - should be empty")
set_ai({"productRecommendations": True})

# Test 4: Customer memory OFF - check that history is not used (hard to test, but we check that AI still responds without history)
print("\n=== Test 4: Customer memory OFF ===")
set_ai({"customerMemory": False})
r=chat("What did I ask before?", [{"id":1,"sender":"customer","content":"I asked about Black Evening Dress","time":"10:00 AM"}])
print("response:", r.get('response')[:100])
print("PASS if response doesn't reference previous (manual check)")
set_ai({"customerMemory": True})

# Test 5: Human handoff OFF
print("\n=== Test 5: Human handoff OFF ===")
set_ai({"humanHandoff": False})
r=chat("I want to speak to a human")
print("requiresHandoff:", r.get('requiresHandoff'))
print("PASS" if not r.get('requiresHandoff') else "FAIL - should not handoff")
set_ai({"humanHandoff": True})

# Test 6: Order assistance OFF
print("\n=== Test 6: Order assistance OFF ===")
set_ai({"orderAssistance": False})
r=chat("I want to place an order for Black Evening Dress")
print("intent:", r.get('intent'), "requiresHandoff:", r.get('requiresHandoff'))
print("PASS" if r.get('requiresHandoff') else "FAIL")
set_ai({"orderAssistance": True})

# Test 7: Response style Friendly
print("\n=== Test 7: Response style Friendly ===")
set_ai({"responseStyle": "Friendly"})
r=chat("Hello")
print("response:", r.get('response')[:150])
print("Check if friendly style (manual)")
set_ai({"responseStyle": "Professional"})

# Test 8: Confidence threshold High
print("\n=== Test 8: Confidence threshold High ===")
set_ai({"confidenceThreshold": "High"})
# Use a vague message that should have low confidence
r=chat("asldkfj asldkfj")
print("confidence:", r.get('confidence'), "requiresHandoff:", r.get('requiresHandoff'))
print("PASS if high threshold causes handoff for low confidence")
set_ai({"confidenceThreshold": "Medium"})

# Restore original
orig_ai = {"enabled": True, "autoReply": True, "productRecommendations": True, "customerMemory": True, "humanHandoff": True, "orderAssistance": True, "responseStyle": "Professional", "confidenceThreshold": "Medium"}
set_ai(orig_ai)
print("\nRestored original AI settings")
print("Final AI settings:", get_ai())

# Test RAG: ensure AI doesn't invent product not in catalog
print("\n=== Test RAG catalog ===")
r=chat("Do you have Unicorn Dress in stock?")
print("productsMentioned:", r.get('productsMentioned'))
# Check if Unicorn Dress is in productsMentioned (should not be, as it's not in catalog)
print("PASS if Unicorn Dress not in productsMentioned and response doesn't invent" if "Unicorn Dress" not in str(r.get('productsMentioned')) else "FAIL")

print("\nAll AI settings tests done")
