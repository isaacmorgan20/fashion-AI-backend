import asyncio
import json
import hmac
import hashlib
import logging
from fastapi.testclient import TestClient
from app.main import app
from app.firebase import initialize_firebase, get_firestore_client

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

initialize_firebase()

client = TestClient(app)

# Test data
seller_id = "sl36LXumSKafrZIW357HBj27iXo2"
secret = "A7F31C9E2B8D44F6A1C7E903D5B82F104C6A7E1B9D3F5A82C1E6B4D9F703A215"
body = '{"update_id":999998,"message":{"message_id":998,"from":{"id":123456789,"is_bot":false,"first_name":"Test","username":"testuser"},"chat":{"id":123456789,"first_name":"Test","username":"testuser","type":"private"},"date":1699999999,"text":"Hi"}}'

headers = {
    "X-Telegram-Bot-Api-Secret-Token": secret,
    "Content-Type": "application/json"
}

print("=" * 60)
print("SENDING TEST WEBHOOK")
print("=" * 60)

response = client.post(f"/api/v1/webhook/telegram/{seller_id}", content=body, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

print("\n" + "=" * 60)
print("CHECKING FIRESTORE")
print("=" * 60)

db = get_firestore_client()

# Check customers
customers_ref = db.collection("users").document(seller_id).collection("customers")
customers = list(customers_ref.where("telegram_id", "==", "123456789").stream())
print(f"Customers found with telegram_id=123456789: {len(customers)}")
for c in customers:
    data = c.to_dict()
    print(f"  Customer ID: {c.id}")
    print(f"  Name: {data.get('name')}")
    print(f"  Telegram ID: {data.get('telegram_id')}")
    print(f"  Chat ID: {data.get('chat_id', 'N/A')}")

# Check conversations
convs_ref = db.collection("users").document(seller_id).collection("conversations")
convs = list(convs_ref.where("channel", "==", "telegram").stream())
print(f"\nTelegram conversations: {len(convs)}")
for c in convs:
    data = c.to_dict()
    print(f"  Conversation ID: {c.id}")
    print(f"  Channel: {data.get('channel')}")
    print(f"  Chat ID: {data.get('chat_id')}")
    print(f"  Phone: {data.get('phone')}")
    print(f"  Messages: {len(data.get('messages', []))}")
    for msg in data.get('messages', [])[-3:]:
        print(f"    - {msg.get('sender')}: {msg.get('content')[:50]}")