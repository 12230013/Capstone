from app.services.qdrant_service import QdrantService

def inspect_database():
    qdrant = QdrantService()
    # Scroll or count points in collection
    collection_info = qdrant.client.get_collection(qdrant.collection_name)
    print(f"Collection Name: {qdrant.collection_name}")
    print(f"Total Vectors stored in Qdrant: {collection_info.points_count}")

if __name__ == "__main__":
    inspect_database()