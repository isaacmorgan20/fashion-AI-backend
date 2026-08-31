#!/usr/bin/env python
"""Script to seed Firestore with initial product data."""
import firebase_admin
from firebase_admin import credentials, firestore
import json
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


def seed_products(user_id: str):
    """Seed products for a specific user."""
    db = firestore.client()
    
    products = [
        {
            "name": "Black Evening Dress",
            "category": "Dresses",
            "price": 450,
            "stock": 12,
            "sizes": ["S", "M", "L"],
            "colors": ["Black"],
            "description": "Elegant black evening dress suitable for weddings, parties and formal events.",
            "image": "https://images.unsplash.com/photo-1566174053879-31528523f8ae?auto=format&fit=crop&w=900&q=80",
            "status": "In stock"
        },
        {
            "name": "Red Summer Dress",
            "category": "Dresses",
            "price": 380,
            "stock": 7,
            "sizes": ["S", "M", "L", "XL"],
            "colors": ["Red"],
            "description": "Lightweight summer dress designed for casual and outdoor occasions.",
            "image": "https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?auto=format&fit=crop&w=900&q=80",
            "status": "In stock"
        },
        {
            "name": "Black Shirt",
            "category": "Men",
            "price": 180,
            "stock": 4,
            "sizes": ["M", "L", "XL"],
            "colors": ["Black"],
            "description": "Classic black shirt with a clean modern fit.",
            "image": "https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?auto=format&fit=crop&w=900&q=80",
            "status": "Low stock"
        },
        {
            "name": "Blue Kaftan",
            "category": "Men",
            "price": 500,
            "stock": 0,
            "sizes": ["M", "L", "XL"],
            "colors": ["Blue"],
            "description": "Premium blue kaftan for traditional and formal occasions.",
            "image": "https://images.unsplash.com/photo-1610652492500-ded49ceeb378?auto=format&fit=crop&w=900&q=80",
            "status": "Out of stock"
        },
        {
            "name": "White Heels",
            "category": "Shoes",
            "price": 250,
            "stock": 9,
            "sizes": ["38", "39", "40", "41"],
            "colors": ["White"],
            "description": "Elegant white heels designed for formal and evening wear.",
            "image": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=900&q=80",
            "status": "In stock"
        },
        {
            "name": "Gold Heels",
            "category": "Shoes",
            "price": 550,
            "stock": 3,
            "sizes": ["38", "39", "40"],
            "colors": ["Gold"],
            "description": "Premium gold heels for special occasions.",
            "image": "https://images.unsplash.com/photo-1560343090-f0409e92791a?auto=format&fit=crop&w=900&q=80",
            "status": "Low stock"
        },
        {
            "name": "Silk Dress",
            "category": "Dresses",
            "price": 900,
            "stock": 6,
            "sizes": ["S", "M", "L"],
            "colors": ["Cream"],
            "description": "Premium silk dress with a refined finish.",
            "image": "https://images.unsplash.com/photo-1566479179817-c0f6d85a3b4f?auto=format&fit=crop&w=900&q=80",
            "status": "In stock"
        },
        {
            "name": "Designer Bag",
            "category": "Accessories",
            "price": 700,
            "stock": 2,
            "sizes": [],
            "colors": ["Brown"],
            "description": "Premium designer-style handbag for everyday and formal use.",
            "image": "https://images.unsplash.com/photo-1584917865442-de89df76afd3?auto=format&fit=crop&w=900&q=80",
            "status": "Low stock"
        },
        {
            "name": "White Shirt",
            "category": "Men",
            "price": 350,
            "stock": 15,
            "sizes": ["M", "L", "XL", "XXL"],
            "colors": ["White"],
            "description": "Classic white shirt suitable for formal and casual styling.",
            "image": "https://images.unsplash.com/photo-1603252109303-2751441dd157?auto=format&fit=crop&w=900&q=80",
            "status": "In stock"
        },
    ]

    products_ref = db.collection("users").document(user_id).collection("products")
    
    for product in products:
        doc_ref = products_ref.document()
        doc_ref.set(product)
        print(f"Created product: {product['name']} (ID: {doc_ref.id})")

    print(f"\nSeeded {len(products)} products for user {user_id}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python seed_products.py <user_uid>")
        print("Get user UID from Firebase Auth console")
        sys.exit(1)
    
    user_id = sys.argv[1]
    
    # Load .env if exists
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\user\OneDrive\Desktop\GENERAL FOLDER\General Project\REACT\Ten Project Work\Fashion code\fashion-AI\.env")
    
    initialize_firebase()
    seed_products(user_id)