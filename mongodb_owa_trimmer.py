from pymongo import MongoClient, errors as pymongo_errors
import os
from dotenv import load_dotenv
import certifi
from datetime import datetime, timezone, timedelta
import pymongo

# Load environment variables from .env file
load_dotenv()  # This line is crucial to load your .env file

MONGODB_URI = os.environ['MONGODB_URI']
OWA_DATABASE_NAME = os.environ['OWA_DATABASE_NAME']
OWA_COLLECTION_NAME = os.environ['OWA_COLLECTION_NAME']

try:
    client = pymongo.MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[OWA_DATABASE_NAME]
    collection = db[OWA_COLLECTION_NAME]

    cutoff_timestamp = int((datetime.now() - timedelta(days=2)).timestamp())

    # Delete documents where BOTH start AND end are older than the cutoff
    result = collection.delete_many({
        "start": {"$lt": cutoff_timestamp},
        "end": {"$lt": cutoff_timestamp}
    })
    print(f"Deleted {result.deleted_count} document(s) where both start and end are older than {datetime.fromtimestamp(cutoff_timestamp)}")

    client.close()
    print("Database operation completed successfully.")

except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}")
except KeyError as e:
    print(f"Missing environment variable: {e}")
except Exception as e:
    print(f"An error occurred: {e}")




    # 2. Delete the N oldest documents (Use with extreme caution!)
    # oldest_documents = collection.find().sort([("created_at", 1)]).limit(10)
    # for doc in oldest_documents:
    #     result = collection.delete_one({"_id": doc["_id"]})
    #     print(f"Deleted document with ID: {doc['_id']}")


    # 3. Delete documents based on a custom condition using $where (least efficient)
    # result = collection.delete_many({"$where": "this.createdAt < Date.now() - 30*24*60*60*1000"}) #30 days in milliseconds
    # print(f"Deleted {result.deleted_count} document(s)")

    client.close()
    print("Database operation completed successfully.")

except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}")
except KeyError as e:
    print(f"Missing environment variable: {e}")
except Exception as e:
    print(f"An error occurred: {e}")