from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


STORAGE_PATH = "qdrant_storage"
COLLECTION_NAME = "investigation_documents"


# --------------------------------------------------
# Step 1: Open existing Qdrant storage
# --------------------------------------------------

client = QdrantClient(
    path=STORAGE_PATH
)


# --------------------------------------------------
# Step 2: Delete the existing collection
# --------------------------------------------------

if client.collection_exists(COLLECTION_NAME):
    client.delete_collection(COLLECTION_NAME)
    print(f"Deleted collection: {COLLECTION_NAME}")


# --------------------------------------------------
# Step 3: Close the old client
# --------------------------------------------------

client.close()


# --------------------------------------------------
# Step 4: Open a completely new Qdrant client
# --------------------------------------------------

client = QdrantClient(
    path=STORAGE_PATH
)


# --------------------------------------------------
# Step 5: Create a fresh collection
# --------------------------------------------------

client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=384,
        distance=Distance.COSINE
    )
)

print(f"Created fresh collection: {COLLECTION_NAME}")


# --------------------------------------------------
# Step 6: Verify the collection is empty
# --------------------------------------------------

count = client.count(
    collection_name=COLLECTION_NAME,
    exact=True
)

print("Point count:", count.count)


# --------------------------------------------------
# Step 7: Close client
# --------------------------------------------------

client.close()