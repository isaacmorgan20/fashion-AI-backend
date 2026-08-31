#!/usr/bin/env python
"""Script to seed Firestore with sample customers for testing."""
import firebase_admin
from firebase_admin import credentials, firestore
import os
import time
from datetime import datetime


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


def seed_customers(user_id: str):
    """Seed sample customers for a specific user."""
    db = firestore.client()

    now = time.time()

    customers = [
        {
            "name": "Sarah Mensah",
            "initials": "SM",
            "phone": "+233 24 123 4567",
            "email": "sarah@example.com",
            "location": "Accra, Ghana",
            "status": "Active",
            "channel": "WhatsApp",
            "orders": 2,
            "totalSpent": 700.0,
            "conversations": 8,
            "lastInteraction": "2 min ago",
            "joined": "August 12, 2026",
            "notes": "Interested in dresses and matching accessories. Usually asks about medium sizes.",
            "products": [
                {"name": "Black Evening Dress", "price": "GHS 450"},
                {"name": "White Heels", "price": "GHS 250"},
            ],
            "ordersList": [
                {"id": "#ORD-1032", "product": "Black Evening Dress", "amount": "GHS 450", "status": "Completed", "date": "Aug 20, 2026"},
                {"id": "#ORD-0984", "product": "White Heels", "amount": "GHS 250", "status": "Completed", "date": "Aug 15, 2026"},
            ],
            "conversationsList": [
                {"date": "Today", "channel": "WhatsApp", "preview": "Can I order the black dress?", "status": "AI handled"},
                {"date": "Aug 20, 2026", "channel": "WhatsApp", "preview": "Do you have size M?", "status": "Order completed"},
                {"date": "Aug 15, 2026", "channel": "Website", "preview": "How much are the white heels?", "status": "AI handled"},
            ],
            "createdAt": now - 3600,
            "updatedAt": now - 120,
            "online": True,
        },
        {
            "name": "John Owusu",
            "initials": "JO",
            "phone": "+233 20 987 6543",
            "email": "john@example.com",
            "location": "Kumasi, Ghana",
            "status": "Active",
            "channel": "Instagram",
            "orders": 1,
            "totalSpent": 180.0,
            "conversations": 4,
            "lastInteraction": "5 min ago",
            "joined": "August 18, 2026",
            "notes": "Waiting for delivery confirmation. Interested in men's clothing.",
            "products": [
                {"name": "Black Shirt", "price": "GHS 180"},
            ],
            "ordersList": [
                {"id": "#ORD-1027", "product": "Black Shirt", "amount": "GHS 180", "status": "Pending", "date": "Aug 24, 2026"},
            ],
            "conversationsList": [
                {"date": "Today", "channel": "Instagram", "preview": "Is delivery available to Kumasi?", "status": "Human handled"},
                {"date": "Aug 24, 2026", "channel": "Instagram", "preview": "How much is the black shirt?", "status": "Order pending"},
            ],
            "createdAt": now - 1800,
            "updatedAt": now - 300,
            "online": False,
        },
        {
            "name": "Ama Boateng",
            "initials": "AB",
            "phone": "+233 27 222 3344",
            "email": "ama@example.com",
            "location": "Kumasi, Ghana",
            "status": "New",
            "channel": "Website",
            "orders": 0,
            "totalSpent": 0.0,
            "conversations": 2,
            "lastInteraction": "8 min ago",
            "joined": "August 26, 2026",
            "notes": "New customer who showed interest in the Red Summer Dress.",
            "products": [
                {"name": "Red Summer Dress", "price": "GHS 380"},
            ],
            "ordersList": [],
            "conversationsList": [
                {"date": "Today", "channel": "Website", "preview": "Do you deliver to Kumasi?", "status": "AI handled"},
                {"date": "Today", "channel": "Website", "preview": "How much is delivery?", "status": "AI handled"},
            ],
            "createdAt": now - 480,
            "updatedAt": now - 480,
            "online": True,
        },
        {
            "name": "Michael Asare",
            "initials": "MA",
            "phone": "+233 55 555 7788",
            "email": "michael@example.com",
            "location": "Tema, Ghana",
            "status": "Repeat",
            "channel": "Facebook",
            "orders": 3,
            "totalSpent": 1250.0,
            "conversations": 12,
            "lastInteraction": "14 min ago",
            "joined": "July 4, 2026",
            "notes": "Repeat customer. Frequently buys men's clothing and responds well to product recommendations.",
            "products": [
                {"name": "Blue Kaftan", "price": "GHS 500"},
                {"name": "Black Trousers", "price": "GHS 400"},
                {"name": "White Shirt", "price": "GHS 350"},
            ],
            "ordersList": [
                {"id": "#ORD-1012", "product": "Blue Kaftan", "amount": "GHS 500", "status": "Completed", "date": "Aug 10, 2026"},
                {"id": "#ORD-0934", "product": "Black Trousers", "amount": "GHS 400", "status": "Completed", "date": "Jul 28, 2026"},
                {"id": "#ORD-0871", "product": "White Shirt", "amount": "GHS 350", "status": "Completed", "date": "Jul 10, 2026"},
            ],
            "conversationsList": [
                {"date": "Today", "channel": "Facebook", "preview": "I want to speak to someone.", "status": "Human requested"},
                {"date": "Aug 10, 2026", "channel": "Facebook", "preview": "Can I get the blue kaftan?", "status": "Order completed"},
                {"date": "Jul 28, 2026", "channel": "WhatsApp", "preview": "Do you still have the black trousers?", "status": "Order completed"},
            ],
            "createdAt": now - 86400,
            "updatedAt": now - 840,
            "online": False,
        },
        {
            "name": "Jennifer Addo",
            "initials": "JA",
            "phone": "+233 50 444 1122",
            "email": "jennifer@example.com",
            "location": "Accra, Ghana",
            "status": "VIP",
            "channel": "Website",
            "orders": 7,
            "totalSpent": 3850.0,
            "conversations": 18,
            "lastInteraction": "25 min ago",
            "joined": "June 14, 2026",
            "notes": "VIP customer and strong repeat purchaser. Usually interested in premium products.",
            "products": [
                {"name": "Silk Dress", "price": "GHS 900"},
                {"name": "Gold Heels", "price": "GHS 550"},
                {"name": "Designer Bag", "price": "GHS 700"},
            ],
            "ordersList": [
                {"id": "#ORD-1042", "product": "Silk Dress", "amount": "GHS 900", "status": "Completed", "date": "Aug 23, 2026"},
                {"id": "#ORD-0990", "product": "Gold Heels", "amount": "GHS 550", "status": "Completed", "date": "Aug 11, 2026"},
            ],
            "conversationsList": [
                {"date": "Today", "channel": "Website", "preview": "Do you have anything new?", "status": "AI handled"},
                {"date": "Aug 23, 2026", "channel": "Website", "preview": "I want the silk dress.", "status": "Order completed"},
            ],
            "createdAt": now - 172800,
            "updatedAt": now - 1500,
            "online": True,
        },
        {
            "name": "Grace Asante",
            "initials": "GA",
            "phone": "+233 59 111 2233",
            "email": "grace@example.com",
            "location": "Accra, Ghana",
            "status": "New",
            "channel": "WhatsApp",
            "orders": 0,
            "totalSpent": 0.0,
            "conversations": 3,
            "lastInteraction": "31 min ago",
            "joined": "August 26, 2026",
            "notes": "Interested in women's dresses and checking available sizes.",
            "products": [
                {"name": "Floral Summer Dress", "price": "GHS 320"},
            ],
            "ordersList": [],
            "conversationsList": [
                {"date": "Today", "channel": "WhatsApp", "preview": "What sizes do you have?", "status": "AI handled"},
            ],
            "createdAt": now - 480,
            "updatedAt": now - 480,
            "online": True,
        },
        {
            "name": "Daniel Kofi",
            "initials": "DK",
            "phone": "+233 54 321 7788",
            "email": "daniel@example.com",
            "location": "Takoradi, Ghana",
            "status": "Repeat",
            "channel": "Instagram",
            "orders": 1,
            "totalSpent": 220.0,
            "conversations": 9,
            "lastInteraction": "42 min ago",
            "joined": "July 12, 2026",
            "notes": "Usually asks about men's tops and available colours.",
            "products": [
                {"name": "Classic Polo", "price": "GHS 220"},
            ],
            "ordersList": [
                {"id": "#ORD-1022", "product": "Classic Polo", "amount": "GHS 220", "status": "Completed", "date": "Aug 21, 2026"},
            ],
            "conversationsList": [
                {"date": "Today", "channel": "Instagram", "preview": "Can I get this in black?", "status": "Human handled"},
            ],
            "createdAt": now - 86400,
            "updatedAt": now - 2520,
            "online": False,
        },
    ]

    customers_ref = db.collection("users").document(user_id).collection("customers")

    for customer in customers:
        doc_ref = customers_ref.document()
        doc_ref.set(customer)
        print(f"Created customer: {customer['name']} (ID: {doc_ref.id})")

    print(f"\nSeeded {len(customers)} customers for user {user_id}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python seed_customers.py <user_uid>")
        print("Get user UID from Firebase Auth console")
        sys.exit(1)

    user_id = sys.argv[1]

    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\user\OneDrive\Desktop\GENERAL FOLDER\General Project\REACT\Ten Project Work\Fashion code\fashion-AI\.env")

    initialize_firebase()
    seed_customers(user_id)