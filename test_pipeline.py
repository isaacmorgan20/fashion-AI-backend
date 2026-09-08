import asyncio
import json
import hmac
import hashlib
from fastapi.testclient import TestClient
from app.main import app
from app.telegram import telegram_service

client = TestClient(app)

# Test data
seller_id = "sl36LXumSKafrZIW357HBj27iXo2"
secret = "A7F31C9E2B8D44F6A1C7E903D5B82F104C6A7E1B9D3F5A82C1E6B4D9F703A215"
body = '{"update_id":999999,"message":{"message_id":999,"from":{"id":123456789,"is_bot":false,"first_name":"Test","username":"testuser"},"chat":{"id":123456789,"first_name":"Test","username":"testuser","type":"private"},"date":1699999999,"text":"Hi"}}'

# Calculate secret token header
hmacsha256 = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256)
signature = hmacsha256.hexdigest()

headers = {
    "X-Telegram-Bot-Api-Secret-Token": secret,
    "Content-Type": "application/json"
}

print("Sending test webhook...")
response = client.post(f"/api/v1/webhook/telegram/{seller_id}", content=body, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")