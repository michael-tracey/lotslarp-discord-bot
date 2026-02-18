import json
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

def upload_data():
    # Initialize Firebase
    # Assumes GOOGLE_APPLICATION_CREDENTIALS is set or default creds work
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    
    json_path = 'lotslarp-sect-map/vampire-timeline-data.json'
    
    print(f"Reading {json_path}...")
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {json_path} not found.")
        return
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return

    print(f"Read {len(data)} locations.")
    
    # Check size just in case, though 100K is fine.
    # Firestore doc limit is 1MB.
    
    doc_ref = db.collection('sect_map_data').document('timeline')
    
    print("Uploading to Firestore (collection='sect_map_data', document='timeline')...")
    
    # Store as a field 'locations'
    try:
        doc_ref.set({
            'locations': data,
            'last_updated': firestore.SERVER_TIMESTAMP
        })
        print("Upload successful!")
    except Exception as e:
        print(f"Error uploading to Firestore: {e}")

if __name__ == "__main__":
    upload_data()
