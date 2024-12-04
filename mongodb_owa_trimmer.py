from pymongo import MongoClient, errors as pymongo_errors
import os
from dotenv import load_dotenv
import certifi
from datetime import datetime, timezone, timedelta
import pymongo

# Load environment variables from .env file
load_dotenv()

MONGODB_URI = os.environ['MONGODB_URI']
WAG_DATABASE_NAME = os.environ['WAG_DATABASE_NAME']
WAG_USERS_COLLECTION_NAME = os.environ['WAG_USERS_COLLECTION_NAME']

try:
    client = pymongo.MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[WAG_DATABASE_NAME]
    collection = db[WAG_USERS_COLLECTION_NAME]

    # --- Deletion Section (unchanged) ---
    cutoff_timestamp = int((datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp()) #Use timezone.utc for consistency

    result = collection.delete_many({
        "start": {"$lt": cutoff_timestamp},
        "end": {"$lt": cutoff_timestamp}
    })
    print(f"Deleted {result.deleted_count} document(s) where both start and end are older than {datetime.fromtimestamp(cutoff_timestamp, tz=timezone.utc)} UTC")

    # --- Insertion Section (added) ---
    new_alert = {
        "msg_type": "Alert",
        "categories": ["Met"],
        "urgency": "Immediate",
        "severity": "Severe",
        "certainty": "Observed",
        "start": int(datetime.now(tz=timezone.utc).timestamp()),
        "end": int((datetime.now(tz=timezone.utc) + timedelta(hours=2)).timestamp()),  # Example end time (2 hours from now)
        "sender": "test@example.com",
        "description": [{"language": "en", "event": "Test Alert", "headline": "Test Alert Headline", "instruction": "Test Alert Instruction"}],
        "alert": {"geometry": {"type": "Point", "coordinates": [-71.0589, 42.3601]}} #Example coordinates - replace with your valid coordinates
    }

    inserted_result = collection.insert_one(new_alert)
    print(f"Inserted document with ID: {inserted_result.inserted_id}")

    client.close()
    print("Database operation completed successfully.")

except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}") # Log the actual exception
except KeyError as e:
    print(f"Missing environment variable: {e}") # Log the actual exception
except Exception as e:
    print(f"An error occurred: {e}") # Log the actual exception
