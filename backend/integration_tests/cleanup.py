"""Remove only a disposable database carrying this run's ownership marker."""
import os
import re
import sys

from pymongo import MongoClient


def remove_owned_database(client, database_name, run_id):
    if not database_name.startswith("acc_test_") or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise RuntimeError("Invalid integration database cleanup request.")
    database = client[database_name]
    if not database.list_collection_names():
        return
    if database.integration_test_runs.find_one({"_id": run_id}) is None:
        raise RuntimeError("Refusing to remove a database owned by another test run.")
    client.drop_database(database_name)


if __name__ == "__main__":
    with MongoClient(os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000) as client:
        remove_owned_database(client, sys.argv[1], sys.argv[2])
    print("Disposable browser database cleanup complete.")
