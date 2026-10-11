import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"

try:
    client = MongoClient(MONGO_URI)
    db = client["acc_database"]
    users_collection = db["users"]
except Exception:
    client = None
    db = None
    users_collection = None
