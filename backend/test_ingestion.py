import os
from app.services.ingestion_service import IngestionService

def test_pipeline():
    # Make sure you have a sample document path ready in your data folder
    sample_pdf_path = "/Users/macbookprom5/Desktop/CAPSTONE/Capstone/backend/data/documents/document.pdf"  # Update with your actual test file path
    
    if not os.path.exists(sample_pdf_path):
        print(f"Test file not found at {sample_pdf_path}. Please update the path to an existing document.")
        return

    print("Initializing IngestionService...")
    ingestion_service = IngestionService()

    print(f"Ingesting document: {sample_pdf_path} ...")
    result = ingestion_service.ingest_document(sample_pdf_path)

    print("Ingestion Successful!")
    print(result)

if __name__ == "__main__":
    test_pipeline()