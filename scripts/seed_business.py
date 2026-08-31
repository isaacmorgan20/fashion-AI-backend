#!/usr/bin/env python
"""Script to seed Firestore with business info for AI context."""
import firebase_admin
from firebase_admin import credentials, firestore
import os


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


def seed_business(user_id: str):
    """Seed business info for a specific user."""
    db = firestore.client()
    
    business_data = {
        "businessName": "ThreadOS Fashion",
        "businessCategory": "Fashion & Apparel",
        "currency": "GHS",
        "timezone": "Africa/Accra",
        "language": "English",
        "businessEmail": "hello@threadosfashion.com",
        "businessPhone": "+233 24 000 0000",
        "createdAt": firestore.SERVER_TIMESTAMP,
    }

    db.collection("users").document(user_id).set(business_data, merge=True)
    print(f"Seeded business info for user {user_id}")
    print(json.dumps(business_data, indent=2, default=str))


if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python seed_business.py <user_uid>")
        print("Get user UID from Firebase Auth console")
        sys.exit(1)
    
    user_id = sys.argv[1]
    
    # Load .env if exists
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\user\OneDrive\Desktop\GENERAL FOLDER\General Project\REACT\Ten Project Work\Fashion code\fashion-AI\.env")
    
    initialize_firebase()
    seed_business(user_id)