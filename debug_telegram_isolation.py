import asyncio
import httpx
import hmac
import hashlib
import json
import time
from app.firebase import initialize_firebase, get_firestore_client

async def test_isolation():
    secret = 'A7F31C9E2B8D44F6A1C7E903D5B82F104C6A7E1B9D3F5A82C1E6B4D9F703A215'
    
    # Test 1: Send message to seller 1's webhook (chat 1175028174 - seller 1's chat)
    payload1 = {
        'update_id': 1000001,
        'message': {
            'message_id': 1001,
            'from': {'id': 1175028174, 'is_bot': False, 'first_name': 'Seller1Customer'},
            'chat': {'id': 1175028174, 'type': 'private'},
            'date': 1790600001,
            'text': 'Hello from Seller 1 customer'
        }
    }
    body1 = json.dumps(payload1).encode('utf-8')
    sig1 = hmac.new(secret.encode('utf-8'), body1, hashlib.sha256).hexdigest()
    headers = {'X-Telegram-Bot-Api-Secret-Token': secret, 'Content-Type': 'application/json'}
    
    url1 = 'https://fashion-ai-backend-wbzm.onrender.com/api/v1/webhook/telegram/BvZM8wp75LTVBWUZeJnt3sj1oIu1'
    async with httpx.AsyncClient() as client:
        resp = await client.post(url1, content=body1, headers=headers)
        print('Test 1 - Seller 1 webhook:', resp.status_code, resp.json())
    
    # Test 2: Send message to seller 2's webhook (chat 7480486807 - seller 2's chat)
    payload2 = {
        'update_id': 2000001,
        'message': {
            'message_id': 2001,
            'from': {'id': 7480486807, 'is_bot': False, 'first_name': 'Seller2Customer'},
            'chat': {'id': 7480486807, 'type': 'private'},
            'date': 1790600002,
            'text': 'Hello from Seller 2 customer'
        }
    }
    body2 = json.dumps(payload2).encode('utf-8')
    sig2 = hmac.new(secret.encode('utf-8'), body2, hashlib.sha256).hexdigest()
    
    url2 = 'https://fashion-ai-backend-wbzm.onrender.com/api/v1/webhook/telegram/sl36LXumSKafrZIW357HBj27iXo2'
    async with httpx.AsyncClient() as client:
        resp = await client.post(url2, content=body2, headers=headers)
        print('Test 2 - Seller 2 webhook:', resp.status_code, resp.json())
    
    # Wait a bit for processing
    time.sleep(2)
    
    # Check conversations
    initialize_firebase()
    db = get_firestore_client()
    
    print()
    print('Checking conversations...')
    
    # Seller 1
    convs = db.collection('users').document('BvZM8wp75LTVBWUZeJnt3sj1oIu1').collection('conversations').stream()
    for conv in convs:
        data = conv.to_dict()
        if data.get('channel') == 'telegram' and data.get('chat_id') == '1175028174':
            msgs = data.get('messages', [])
            last = msgs[-1] if msgs else {}
            sender = last.get('sender')
            content = last.get('content', '')[:50]
            print('Seller 1 chat 1175028174: last msg = {}: {}'.format(sender, content))
    
    # Seller 2
    convs = db.collection('users').document('sl36LXumSKafrZIW357HBj27iXo2').collection('conversations').stream()
    for conv in convs:
        data = conv.to_dict()
        if data.get('channel') == 'telegram' and data.get('chat_id') == '7480486807':
            msgs = data.get('messages', [])
            last = msgs[-1] if msgs else {}
            sender = last.get('sender')
            content = last.get('content', '')[:50]
            print('Seller 2 chat 7480486807: last msg = {}: {}'.format(sender, content))
    
    # Cross-check: ensure seller 1 doesn't have seller 2's chat and vice versa
    print()
    print('Cross-check isolation:')
    convs1 = list(db.collection('users').document('BvZM8wp75LTVBWUZeJnt3sj1oIu1').collection('conversations').stream())
    seller1_chats = [c.to_dict().get('chat_id') for c in convs1 if c.to_dict().get('channel') == 'telegram']
    print('Seller 1 telegram chats:', seller1_chats)
    
    convs2 = list(db.collection('users').document('sl36LXumSKafrZIW357HBj27iXo2').collection('conversations').stream())
    seller2_chats = [c.to_dict().get('chat_id') for c in convs2 if c.to_dict().get('channel') == 'telegram']
    print('Seller 2 telegram chats:', seller2_chats)
    
    overlap = set(seller1_chats) & set(seller2_chats)
    print('Overlapping chats:', overlap)
    if not overlap:
        print('ISOLATION WORKING: No overlapping chat_ids between sellers!')
    else:
        print('ISOLATION BROKEN: Found overlapping chats!')

if __name__ == '__main__':
    asyncio.run(test_isolation())