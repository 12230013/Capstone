# import os
# from pymongo import MongoClient
# from dotenv import load_dotenv

# load_dotenv()

# MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"

# try:
#     client = MongoClient(MONGO_URI)
#     db = client["acc_database"]
#     users_collection = db["users"]
# except Exception:
#     client = None
#     db = None
#     users_collection = None


## MINE

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"

try:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=20000,
    )
    db = client[os.getenv("MONGO_DB_NAME", "acc_database")]

    # Collections
    users_collection = db["users"]
    conversations_collection = db["conversations"]
    messages_collection = db["messages"]
    folders_collection = db["folders"]
    activity_collection = db["activity"]
    sessions_collection = db["sessions"]
    ocr_documents_collection = db["ocr_documents"]
    cims_sync_collection = db["cims_sync_records"]
    

except Exception:
    client = None
    db = None
    users_collection = None
    conversations_collection = None
    messages_collection = None
    folders_collection = None
    activity_collection = None
    sessions_collection = None
    ocr_documents_collection = None
    cims_sync_collection = None
