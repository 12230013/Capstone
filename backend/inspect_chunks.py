from app.services.qdrant_service import QdrantService

def inspect_db():
    qdrant = QdrantService()
    
    # Scroll through records stored in Qdrant
    records, _ = qdrant.client.scroll(
        collection_name=qdrant.collection_name,
        with_payload=True,
        with_vectors=False,
        limit=10
    )
    
    print(f"--- Displaying Stored Chunks (Total fetched: {len(records)}) ---\n")
    for record in records:
        print(f"Point ID: {record.id}")
        print(f"Payload Text:\n{record.payload.get('text')}")
        print(f"Metadata: {record.payload.get('metadata')}")
        print("-" * 50)

if __name__ == "__main__":
    inspect_db()