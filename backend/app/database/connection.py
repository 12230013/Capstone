import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI, authSource="admin")

db = client["acc_database"]

users_collection = db["users"]
password_reset_collection = db["password_reset_otps"]