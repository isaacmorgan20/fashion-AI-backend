#!/usr/bin/env python
"""Script to seed Firestore with sample conversations for testing."""
import firebase_admin
from firebase_admin import credentials, firestore
import os
import time


def initialize_firebase():
    """Initialize Firebase Admin SDK from env."""
    if firebase_admin._apps:
        return

    project_id = os.getenv("FIREBASE_PROJECT_ID", "fashion-22af0")
    private_key = os.getenv("FIREBASE_PRIVATE_KEY")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")

    if not private_key or not client_email:
        print("Firebase credentials not configured in environment")
        return

    cred_dict = {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": private_key.replace("\\n", "\n"),
        "client_email": client_email,
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    }

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)


def seed_conversations(user_id: str):
    """Seed sample conversations for a specific user."""
    db = firestore.client()
    
    now = time.time()
    
    conversations = [
        {
            "name": "Sarah Mensah",
            "initials": "SM",
            "status": "online",
            "channel": "WhatsApp",
            "lastMessage": "Can I order the black dress?",
            "time": "2m",
            "unread": 2,
            "mode": "ai",
            "conversationStatus": "open",
            "phone": "+233 24 123 4567",
            "email": "sarah@example.com",
            "location": "Accra, Ghana",
            "orders": [
                {"id": "#ORD-1032", "product": "Black Evening Dress", "amount": "GHS 450", "status": "Completed"},
                {"id": "#ORD-0984", "product": "White Heels", "amount": "GHS 250", "status": "Completed"},
            ],
            "productsDiscussed": ["Black Evening Dress", "White Heels"],
            "messages": [
                {"id": 1, "sender": "customer", "content": "Hi, is this dress still available?", "time": "10:41 AM"},
                {"id": 2, "sender": "ai", "content": "Hi Sarah! Yes, the Black Evening Dress is currently available.", "time": "10:42 AM"},
                {"id": 3, "sender": "customer", "content": "Do you have size M?", "time": "10:43 AM"},
                {"id": 4, "sender": "ai", "content": "Yes, size M is available. The price is GHS 450. Would you like to order it?", "time": "10:43 AM"},
                {"id": 5, "sender": "customer", "content": "Can I order the black dress?", "time": "10:45 AM"},
            ],
            "createdAt": now - 3600,
            "updatedAt": now - 120,
        },
        {
            "name": "John Owusu",
            "initials": "JO",
            "status": "offline",
            "channel": "Instagram",
            "lastMessage": "How much is the black shirt?",
            "time": "5m",
            "unread": 0,
            "mode": "human",
            "conversationStatus": "open",
            "phone": "+233 20 987 6543",
            "email": "john@example.com",
            "location": "Kumasi, Ghana",
            "orders": [
                {"id": "#ORD-1027", "product": "Black Shirt", "amount": "GHS 180", "status": "Pending"},
            ],
            "productsDiscussed": ["Black Shirt"],
            "messages": [
                {"id": 1, "sender": "customer", "content": "Hello, how much is the black shirt?", "time": "10:35 AM"},
                {"id": 2, "sender": "human", "content": "Hi John, the black shirt is GHS 180.", "time": "10:36 AM"},
                {"id": 3, "sender": "customer", "content": "Is delivery available to Kumasi?", "time": "10:38 AM"},
            ],
            "createdAt": now - 1800,
            "updatedAt": now - 300,
        },
        {
            "name": "Ama Boateng",
            "initials": "AB",
            "status": "online",
            "channel": "Website",
            "lastMessage": "Do you deliver to Kumasi?",
            "time": "8m",
            "unread": 1,
            "mode": "ai",
            "conversationStatus": "open",
            "phone": "+233 27 222 3344",
            "email": "ama@example.com",
            "location": "Kumasi, Ghana",
            "orders": [],
            "productsDiscussed": ["Red Summer Dress"],
            "messages": [
                {"id": 1, "sender": "customer", "content": "Do you deliver to Kumasi?", "time": "10:30 AM"},
                {"id": 2, "sender": "ai", "content": "Yes, we deliver to Kumasi. Delivery usually takes 1–2 business days.", "time": "10:31 AM"},
            ],
            "createdAt": now - 480,
            "updatedAt": now - 480,
        },
        {
            "name": "Michael Asare",
            "initials": "MA",
            "status": "offline",
            "channel": "Facebook",
            "lastMessage": "I want to speak to someone.",
            "time": "14m",
            "unread": 1,
            "mode": "handoff",
            "conversationStatus": "handed_off",
            "phone": "+233 55 555 7788",
            "email": "michael@example.com",
            "location": "Tema, Ghana",
            "orders": [],
            "productsDiscussed": ["Blue Kaftan"],
            "messages": [
                {"id": 1, "sender": "customer", "content": "I have a problem with my order.", "time": "10:18 AM"},
                {"id": 2, "sender": "ai", "content": "I'm sorry you're experiencing a problem. I'll connect you with a human support agent.", "time": "10:19 AM"},
                {"id": 3, "sender": "customer", "content": "I want to speak to someone.", "time": "10:20 AM"},
            ],
            "createdAt": now - 840,
            "updatedAt": now - 840,
        },
    ]

    conv_ref = db.collection("users").document(user_id).collection("conversations")
    
    for conv in conversations:
        doc_ref = conv_ref.document()
        doc_ref.set(conv)
        print(f"Created conversation: {conv['name']} (ID: {doc_ref.id})")

    print(f"\nSeeded {len(conversations)} conversations for user {user_id}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python seed_conversations.py <user_uid>")
        print("Get user UID from Firebase Auth console")
        sys.exit(1)
    
    user_id = sys.argv[1]
    
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\user\OneDrive\Desktop\GENERAL FOLDER\General Project\REACT\Ten Project Work\Fashion code\fashion-AI\.env")
    
    initialize_firebase()
    seed_conversations(user_id)