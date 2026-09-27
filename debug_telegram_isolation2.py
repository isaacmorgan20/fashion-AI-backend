import asyncio
import httpx
import hmac
import hashlib
import json
import time
from app.firebase import initialize_firebase, get_firestore_client

async def test_isolation_new_chats():
    secret = 'A7F31C9E2B8D44F6A1C7E903D5B82F104C6A7E1B9D3F5A82C1E6B4D9F703A215'
    
    # Use NEW chat_ids that don't exist in either seller's database
    NEW_CHAT_ID_1 = '999999991'  # New customer for seller 1
    NEW_CHAT_ID_2 = '999999992'  # New customer for seller 2
    
    # Test 1: Send message to seller 1's webhook with NEW chat_id
    payload1 = {
        'update_id': 999999991,
        'message': {
            'message_id': 999999991,
            'from': {'id': int(NEW_CHAT_ID_1), 'is_bot': False, 'first_name': 'NewCustomer1'},
            'chat': {'id': int(NEW_CHAT_ID_1), 'type': 'private'},
            'date': 1790600001,
            'text': 'Hello from NEW Seller 1 customer'
        }
    }
    body1 = json.dumps(payload1).encode('utf-8')
    sig1 = hmac.new(secret.encode('utf-8'), body1, hashlib.sha256).hexdigest()
    headers = {'X-Telegram-Bot-Api-Secret-Token': secret, 'Content-Type': 'application/json'}
    
    url1 = 'https://fashion-ai-backend-wbzm.onrender.com/api/v1/webhook/telegram/BvZM8wp75LTVBWUZeJnt3sj1oIu1'
    async with httpx.AsyncClient() as client:
        resp = await client.post(url1, content=body1, headers=headers)
        print('Test 1 - Seller 1 webhook (new chat):', resp.status_code, resp.json())
    
    # Test 2: Send message to seller 2's webhook with NEW chat_id
    payload2 = {
        'update_id': 999999992,
        'message': {
            'message_id': 999999992,
            'from': {'id': int(NEW_CHAT_ID_2), 'is_bot': False, 'first_name': 'NewCustomer2'},
            'chat': {'id': int(NEW_CHAT_ID_2), 'type': 'private'},
            'date': 1790600002,
            'text': 'Hello from NEW Seller 2 customer'
        }
    }
    body2 = json.dumps(payload2).encode('utf-8')
    sig2 = hmac.new(secret.encode('utf-8'), body2, hashlib.sha256).hexdigest()
    
    url2 = 'https://fashion-ai-backend-wbzm.onrender.com/api/v1/webhook/telegram/sl36LXumSKafrZIW357HBj27iXo2'
    async with httpx.AsyncClient() as client:
        resp = await client.post(url2, content=body2, headers=headers)
        print('Test 2 - Seller 2 webhook (new chat):', resp.status_code, resp.json())
    
    # Wait a bit for processing
    time.sleep(2)
    
    # Check conversations
    initialize_firebase()
    db = get_firestore_client()
    
    print()
    print('Checking NEW conversations...')
    
    # Seller 1 - should have NEW_CHAT_ID_1
    convs = db.collection('users').document('BvZM8wp75LTVBWUZeJnt3sj1oIu1').collection('conversations').stream()
    for conv in convs:
        data = conv.to_dict()
        if data.get('channel') == 'telegram' and data.get('chat_id') == NEW_CHAT_ID_1:
            msgs = data.get('messages', [])
            last = msgs[-1] if msgs else {}
            sender = last.get('sender')
            content = last.get('content', '')[:50]
            print('Seller 1 NEW chat {}: last msg = {}: {}'.format(NEW_CHAT_ID_1, sender, content))
    
    # Seller 2 - should have NEW_CHAT_ID_2
    convs = db.collection('users').document('sl36LXumSKafrZIW357HBj27iXo2').collection('conversations').stream()
    for conv in convs:
        data = conv.to_dict()
        if data.get('channel') == 'telegram' and data.get('chat_id') == NEW_CHAT_ID_2:
            msgs = data.get('messages', [])
            last = msgs[-1] if msgs else {}
            sender = last.get('sender')
            content = last.get('content', '')[:50]
            print('Seller 2 NEW chat {}: last msg = {}: {}'.format(NEW_CHAT_ID_2, sender, content))
    
    # Cross-check: ensure seller 1 doesn't have seller 2's NEW chat and vice versa
    print()
    print('Cross-check NEW chats isolation:')
    convs1 = list(db.collection('users').document('BvZM8wp75LTVBWUZeJnt3sj1oIu1').collection('conversations').stream())
    seller1_chats = [c.to_dict().get('chat_id') for c in convs1 if c.to_dict().get('channel') == 'telegram']
    print('Seller 1 telegram chats:', seller1_chats)
    
    convs2 = list(db.collection('users').document('sl36LXumSKafrZIW357HBj27iXo2').collection('conversations').stream())
    seller2_chats = [c.to_dict().get('chat_id') for c in convs2 if c.to_dict().get('channel') == 'telegram']
    print('Seller 2 telegram chats:', seller2_chats)
    
    # Check specifically for the new chats
    has_new_1_in_seller1 = NEW_CHAT_ID_1 in seller1_chats
    has_new_1_in_seller2 = NEW_CHAT_ID_1 in seller2_chats
    has_new_2_in_seller1 = NEW_CHAT_ID_2 in seller1_chats
    has_new_2_in_seller2 = NEW_CHAT_ID_2 in seller2_chats
    
    print()
    print('NEW_CHAT_ID_1 ({}) in Seller 1: {}'.format(NEW_CHAT_ID_1, has_new_1_in_seller1))
    print('NEW_CHAT_ID_1 ({}) in Seller 2: {}'.format(NEW_CHAT_ID_1, has_new_1_in_seller2))
    print('NEW_CHAT_ID_2 ({}) in Seller 1: {}'.format(NEW_CHAT_ID_2, has_new_2_in_seller1))
    print('NEW_CHAT_ID_2 ({}) in Seller 2: {}'.format(NEW_CHAT_ID_2, has_new_2_in_seller2))
    
    if has_new_1_in_seller1 and not has_new_1_in_seller2 and has_new_2_in_seller2 and not has_new_2_in_seller1:
        print()
        print('SUCCESS: Complete isolation verified!')
        print('  - Seller 1 only received messages for their chat')
        print('  - Seller 2 only received messages for their chat')
        print('  - No cross-contamination')
    else:
        print()
        print('FAILURE: Isolation broken!')
        if has_new_1_in_seller2:
            print('  - Seller 2 received Seller 1 message (WRONG)')
        if has_new_2_in_seller1:
            print('  - Seller 1 received Seller 2 message (WRONG)')

if __name__ == '__main__':
    asyncio.run(test_isolation_new_chats())