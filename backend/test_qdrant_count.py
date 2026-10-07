from app.services.qdrant_service import QdrantService


qdrant_service = QdrantService()

collection_name = qdrant_service.collection_name

count = qdrant_service.client.count(
    collection_name=collection_name,
    exact=True
)

print("Collection:", collection_name)
print("Point count:", count.count)

qdrant_service.client.close()