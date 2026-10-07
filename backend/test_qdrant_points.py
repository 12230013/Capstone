from app.services.qdrant_service import QdrantService

qdrant_service = QdrantService()

results = qdrant_service.client.scroll(
    collection_name=qdrant_service.collection_name,
    limit=10,
    with_payload=True,
    with_vectors=True
)

points = results[0]

print("\nStored Qdrant points:")
print("=" * 60)

for point in points:
    print("Point ID:", point.id)
    print("ID type:", type(point.id))
    print("Vector length:", len(point.vector))
    print("Payload:", point.payload)
    print("=" * 60)
    
qdrant_service.client.close()