import uvicorn
import threading
import time
import requests

def run_server():
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, log_level='warning')

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(3)

url = 'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=AIzaSyBPvgPEN8916bKwMZlz1_NR487NFijAApo'
resp = requests.post(url, json={'email': 'test@example.com', 'password': 'testpassword123', 'returnSecureToken': True})
tok = resp.json().get('idToken')
h = {'Authorization': 'Bearer ' + tok}

def chat(msg, history=None):
    if history is None:
        history = []
    convs = requests.get('http://127.0.0.1:8000/api/v1/conversations', headers=h).json()
    if convs:
        cid = convs[0]['id']
    else:
        cr = requests.post('http://127.0.0.1:8000/api/v1/conversations', headers=h, json={'name': 'Test', 'initials': 'TT', 'channel': 'Website'})
        cid = cr.json().get('id')
    payload = {'message': msg, 'conversationId': cid, 'conversationHistory': history}
    r = requests.post('http://127.0.0.1:8000/api/v1/chat', headers=h, json=payload)
    return r.json()

print('=== SCOPE GATE TESTS (should be out_of_scope) ===')
scope_tests = [
    ('Who won the election?', 'politics'),
    ('How to treat a headache?', 'medical'),
    ('What is the capital of France?', 'general knowledge'),
    ('Football scores today', 'sports'),
    ('Python programming tutorial', 'technical'),
    ('Invest in bitcoin', 'financial'),
    ('Legal advice for divorce', 'legal'),
    ('Zara dress prices', 'other_brands'),
    ('My boyfriend broke up with me', 'personal'),
    ('Netflix new movies', 'entertainment'),
    ('Homework help math', 'education'),
]

for msg, category in scope_tests:
    r = chat(msg)
    status = 'PASS' if r.get('intent') == 'out_of_scope' else 'FAIL'
    print(status + ' ' + category + ': intent=' + str(r.get('intent')) + ', handoff=' + str(r.get('requiresHandoff')))

print('\n=== IN-SCOPE TESTS (should be handled normally) ===')
in_scope_tests = [
    ('Hi there!', 'greeting'),
    ('What dresses do you have?', 'product'),
    ('Price of Black Evening Dress', 'price'),
    ('What is your return policy?', 'policy'),
    ('Track my order #123', 'order'),
    ('Contact phone number', 'business'),
    ('Gift for wedding', 'fashion_help'),
    ('Speak to human', 'handoff'),
]

for msg, category in in_scope_tests:
    r = chat(msg)
    status = 'PASS' if r.get('intent') != 'out_of_scope' else 'FAIL'
    print(status + ' ' + category + ': intent=' + str(r.get('intent')) + ', handoff=' + str(r.get('requiresHandoff')))

print('\n=== RAG TEST (unknown product) ===')
r = chat('Do you have Unicorn Dress in stock?')
print('intent=' + str(r.get('intent')) + ', products=' + str(r.get('productsMentioned')))

print('\n=== CONFIDENCE THRESHOLD TEST ===')
# Need to set confidence threshold via settings API
def set_ai(patch):
    r = requests.patch('http://127.0.0.1:8000/api/v1/settings', headers=h, json={'ai': patch})
    return r.json().get('ai')

set_ai({'confidenceThreshold': 'High'})
r = chat('asldkfj asldkfj')
print('High threshold: confidence=' + str(r.get('confidence')) + ', handoff=' + str(r.get('requiresHandoff')))
set_ai({'confidenceThreshold': 'Medium'})

print('\nAll tests completed!')