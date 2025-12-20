import csv
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def upload_glossary(csv_path: str):
    """
    Reads a CSV file and upserts it into the 'lore_glossary' Firestore collection.
    """
    if not os.path.exists(csv_path):
        logger.warning(f"Glossary CSV not found at {csv_path}. Skipping upload.")
        return

    # Initialize Firestore (assumes GOOGLE_APPLICATION_CREDENTIALS or implicit env)
    if not firebase_admin._apps:
        try:
            firebase_admin.initialize_app()
        except Exception as e:
            logger.error(f"Failed to initialize Firebase app: {e}")
            return

    db = firestore.client()
    collection_ref = db.collection('lore_glossary')
    
    batch = db.batch()
    batch_count = 0
    total_processed = 0

    logger.info(f"Starting glossary upload from {csv_path}...")

    try:
        with open(csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                title = row.get('title', '').strip()
                content = row.get('content', '').strip()
                keywords_raw = row.get('keywords', '').strip()
                
                if not title or not content:
                    continue

                # Parse keywords: split by comma, strip whitespace, lowercase
                keywords_list = [k.strip().lower() for k in keywords_raw.split(',') if k.strip()]
                # Always include the title itself as a keyword
                if title.lower() not in keywords_list:
                    keywords_list.append(title.lower())

                # Create document ID from the title (safe string)
                # We'll use a normalized version of the title as the ID to allow easy upserts
                doc_id = "".join(x for x in title if x.isalnum() or x in " -_").strip().lower().replace(" ", "_")
                
                doc_ref = collection_ref.document(doc_id)
                
                data = {
                    'title': title,
                    'content': content,
                    'keywords': keywords_list,
                    'updated_at': datetime.utcnow()
                }

                batch.set(doc_ref, data, merge=True)
                batch_count += 1
                total_processed += 1

                # Commit in batches of 500 (Firestore limit)
                if batch_count >= 400:
                    batch.commit()
                    logger.info(f"Committed batch of {batch_count} records.")
                    batch = db.batch()
                    batch_count = 0

        # Commit remaining
        if batch_count > 0:
            batch.commit()
            logger.info(f"Committed final batch of {batch_count} records.")

        logger.info(f"Glossary upload complete. Processed {total_processed} entries.")

    except Exception as e:
        logger.error(f"Error processing CSV: {e}")

if __name__ == "__main__":
    # Path to the glossary CSV
    csv_file_path = "glossary.csv"
    upload_glossary(csv_file_path)
