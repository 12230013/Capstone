from app.services.ingestion_service import IngestionService

ingestion_service = IngestionService()

files = [
    "test_documents/test.pdf",
    "test_documents/case_002.txt",
    "test_documents/case_003.txt"
]

for file_path in files:
    result = ingestion_service.ingest_document(file_path)

    print("\nIngestion completed:")
    print("Filename:", result["filename"])
    print("Chunks created:", result["chunks_created"])

ingestion_service.qdrant_service.client.close()