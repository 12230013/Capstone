# from app.services.ingestion_service import IngestionService

# ingestion_service = IngestionService()
# result = ingestion_service.ingest_document(
#     "test_documents/test.pdf"
# )

# print("\nIngestion completed.")
# print("Filename:", result["filename"])
# print("Chunks created:", result["chunks_created"])

# ingestion_service.qdrant_service.client.close()
from app.services.ingestion_service import IngestionService


ingestion_service = IngestionService()


file_path = "test_documents/case_004.txt"


result = ingestion_service.ingest_document(file_path)


print("\n" + "=" * 70)
print("INGESTION RESULT")
print("=" * 70)

print("Filename:", result["filename"])
print("Chunks created:", result["chunks_created"])


ingestion_service.qdrant_service.client.close()