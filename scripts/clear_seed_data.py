#!/usr/bin/env python
"""
DEVELOPMENT ONLY - Clear seed/demo data from Firestore.

This script removes ONLY records created by the seed scripts:
- seed_conversations.py (Sarah Mensah, John Owusu, Ama Boateng, Michael Asare)
- seed_customers.py (Sarah Mensah, John Owusu, Ama Boateng, Michael Asare, Jennifer Addo, Grace Asante, Daniel Kofi)
- seed_products.py (Black Evening Dress, Red Summer Dress, Black Shirt, Blue Kaftan, White Heels, Gold Heels, Silk Dress, Designer Bag, White Shirt)

WARNING: This modifies Firestore directly. Run ONLY against development.
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os
import sys
from typing import List, Dict, Any, Tuple

# Seed data identifiers - ONLY these will be deleted
SEED_CUSTOMER_NAMES = [
    "Sarah Mensah",
    "John Owusu", 
    "Ama Boateng",
    "Michael Asare",
    "Jennifer Addo",
    "Grace Asante",
    "Daniel Kofi",
]

SEED_CONVERSATION_NAMES = [
    "Sarah Mensah",
    "John Owusu",
    "Ama Boateng", 
    "Michael Asare",
]

SEED_PRODUCT_NAMES = [
    "Black Evening Dress",
    "Red Summer Dress",
    "Black Shirt",
    "Blue Kaftan",
    "White Heels",
    "Gold Heels",
    "Silk Dress",
    "Designer Bag",
    "White Shirt",
]

# Known seed phone numbers
SEED_PHONES = [
    "+233 24 123 4567",
    "+233 20 987 6543", 
    "+233 27 222 3344",
    "+233 55 555 7788",
    "+233 50 444 1122",
    "+233 59 111 2233",
    "+233 54 321 7788",
]

# Known seed emails
SEED_EMAILS = [
    "sarah@example.com",
    "john@example.com",
    "ama@example.com",
    "michael@example.com",
    "jennifer@example.com",
    "grace@example.com",
    "daniel@example.com",
]

# Known seed order IDs
SEED_ORDER_IDS = [
    "#ORD-1032", "#ORD-0984", "#ORD-1027", "#ORD-1012", 
    "#ORD-0934", "#ORD-0871", "#ORD-1042", "#ORD-0990",
    "#ORD-1022"
]


def initialize_firebase():
    """Initialize Firebase Admin SDK from env."""
    if firebase_admin._apps:
        return

    project_id = os.getenv("FIREBASE_PROJECT_ID", "fashion-22af0")
    private_key = os.getenv("FIREBASE_PRIVATE_KEY")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")

    if not private_key or not client_email:
        print("ERROR: Firebase credentials not configured in environment")
        return False

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
    return True


def find_seed_seller(db) -> str:
    """Find the seller UID that has seed data by checking for seed customers."""
    users_ref = db.collection("users")
    users = users_ref.stream()
    
    for user in users:
        user_id = user.id
        customers_ref = db.collection("users").document(user_id).collection("customers")
        customers = list(customers_ref.limit(10).stream())
        
        for cust in customers:
            data = cust.to_dict()
            if data.get("name") in SEED_CUSTOMER_NAMES:
                print(f"Found seed data for seller: {user_id}")
                return user_id
    
    return None


def is_seed_customer(data: Dict[str, Any]) -> bool:
    """Check if a customer record is seed data."""
    name = data.get("name", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    
    return (
        name in SEED_CUSTOMER_NAMES or
        phone in SEED_PHONES or
        email in SEED_EMAILS
    )


def is_seed_conversation(data: Dict[str, Any]) -> bool:
    """Check if a conversation record is seed data."""
    name = data.get("name", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    orders = data.get("orders", [])
    
    # Check for seed order IDs in orders
    has_seed_order = any(
        order.get("id") in SEED_ORDER_IDS 
        for order in orders if isinstance(order, dict)
    )
    
    return (
        name in SEED_CONVERSATION_NAMES or
        phone in SEED_PHONES or
        email in SEED_EMAILS or
        has_seed_order
    )


def is_seed_product(data: Dict[str, Any]) -> bool:
    """Check if a product record is seed data."""
    name = data.get("name", "")
    return name in SEED_PRODUCT_NAMES


def is_seed_order(data: Dict[str, Any]) -> bool:
    """Check if an order record is seed data."""
    order_id = data.get("id", "") or data.get("orderId", "")
    return order_id in SEED_ORDER_IDS


def scan_and_collect(db, user_id: str) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
    """Scan all collections and collect seed records to delete."""
    results = {
        "conversations": [],
        "customers": [],
        "products": [],
        "orders": [],
    }
    
    # Scan conversations
    conv_ref = db.collection("users").document(user_id).collection("conversations")
    for doc in conv_ref.stream():
        data = doc.to_dict()
        if is_seed_conversation(data):
            results["conversations"].append((doc.id, data))
    
    # Scan customers
    cust_ref = db.collection("users").document(user_id).collection("customers")
    for doc in cust_ref.stream():
        data = doc.to_dict()
        if is_seed_customer(data):
            results["customers"].append((doc.id, data))
    
    # Scan products
    prod_ref = db.collection("users").document(user_id).collection("products")
    for doc in prod_ref.stream():
        data = doc.to_dict()
        if is_seed_product(data):
            results["products"].append((doc.id, data))
    
    # Scan orders
    orders_ref = db.collection("users").document(user_id).collection("orders")
    for doc in orders_ref.stream():
        data = doc.to_dict()
        if is_seed_order(data):
            results["orders"].append((doc.id, data))
    
    return results


def print_summary(results: Dict[str, List]) -> None:
    """Print a summary of records to be deleted."""
    print("\n" + "=" * 60)
    print("SEED DATA CLEANUP PREVIEW")
    print("=" * 60)
    
    total = 0
    for collection, items in results.items():
        count = len(items)
        total += count
        print(f"\n{collection.upper()}: {count}")
        for doc_id, data in items:
            name = data.get("name", data.get("id", doc_id))
            print(f"  - {name} (ID: {doc_id})")
    
    print(f"\n{'=' * 60}")
    print(f"TOTAL RECORDS TO DELETE: {total}")
    print(f"{'=' * 60}\n")


def confirm_deletion() -> bool:
    """Prompt user for confirmation."""
    while True:
        response = input("Proceed with deletion? [y/N]: ").strip().lower()
        if response in ('y', 'yes'):
            return True
        elif response in ('n', 'no', ''):
            return False
        print("Please enter 'y' or 'n'")


def delete_records(db, user_id: str, results: Dict[str, List]) -> Dict[str, int]:
    """Delete the identified seed records."""
    deleted_counts = {"conversations": 0, "customers": 0, "products": 0, "orders": 0}
    
    # Delete conversations
    conv_ref = db.collection("users").document(user_id).collection("conversations")
    for doc_id, _ in results["conversations"]:
        conv_ref.document(doc_id).delete()
        deleted_counts["conversations"] += 1
        print(f"  Deleted conversation: {doc_id}")
    
    # Delete customers
    cust_ref = db.collection("users").document(user_id).collection("customers")
    for doc_id, _ in results["customers"]:
        cust_ref.document(doc_id).delete()
        deleted_counts["customers"] += 1
        print(f"  Deleted customer: {doc_id}")
    
    # Delete products
    prod_ref = db.collection("users").document(user_id).collection("products")
    for doc_id, _ in results["products"]:
        prod_ref.document(doc_id).delete()
        deleted_counts["products"] += 1
        print(f"  Deleted product: {doc_id}")
    
    # Delete orders
    orders_ref = db.collection("users").document(user_id).collection("orders")
    for doc_id, _ in results["orders"]:
        orders_ref.document(doc_id).delete()
        deleted_counts["orders"] += 1
        print(f"  Deleted order: {doc_id}")
    
    return deleted_counts


def main():
    print("=" * 60)
    print("THREADOS SEED DATA CLEANUP - DEVELOPMENT ONLY")
    print("=" * 60)
    
    # Safety check: ensure we're in development
    env = os.getenv("APP_ENV", "development")
    if env == "production":
        print("ERROR: This script refuses to run in production environment!")
        print("Set APP_ENV=development to run, but ONLY on development databases.")
        sys.exit(1)
    
    print(f"Environment: {env}")
    print("Loading .env...")
    
    # Load .env
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\user\OneDrive\Desktop\GENERAL FOLDER\General Project\REACT\Ten Project Work\Fashion code\fashion-AI\.env")
    
    print("Initializing Firebase...")
    if not initialize_firebase():
        sys.exit(1)
    
    db = firestore.client()
    
    print("Scanning for seed data...")
    user_id = find_seed_seller(db)
    
    if not user_id:
        print("ERROR: Could not find a seller with seed data.")
        print("The seed data may already be cleaned up, or the seller UID is different.")
        sys.exit(1)
    
    print(f"Found seller UID: {user_id}")
    
    results = scan_and_collect(db, user_id)
    
    if all(len(v) == 0 for v in results.values()):
        print("\nNo seed data found to clean up.")
        sys.exit(0)
    
    print_summary(results)
    
    if not confirm_deletion():
        print("Cleanup cancelled by user.")
        sys.exit(0)
    
    print("\nDeleting records...")
    deleted = delete_records(db, user_id, results)
    
    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)
    print(f"Conversations deleted: {deleted['conversations']}")
    print(f"Customers deleted: {deleted['customers']}")
    print(f"Products deleted: {deleted['products']}")
    print(f"Orders deleted: {deleted['orders']}")
    print(f"Total: {sum(deleted.values())}")
    
    # Verify
    print("\nVerifying cleanup...")
    remaining = scan_and_collect(db, user_id)
    remaining_total = sum(len(v) for v in remaining.values())
    if remaining_total == 0:
        print("SUCCESS: All seed data removed.")
    else:
        print(f"WARNING: {remaining_total} seed records remain.")
        print_summary(remaining)


if __name__ == "__main__":
    main()