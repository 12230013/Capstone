from app.services.qdrant_service import QdrantService

qdrant_service = QdrantService()

print("Qdrant setup successful.")

qdrant_service.client.close()