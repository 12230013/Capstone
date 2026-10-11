from app.ocr.document_ocr_2 import run_document_ocr

result = run_document_ocr(
    file_path="/Users/macbookprom5/Desktop/CapstoneOCR/Capstone/backend/app/ocr/test.png",
    document_id="test-001",
    filename="test_document.pdf",
    file_type="application/pdf",
)

print("Status:", result["ocr_status"])
print("Engine:", result["ocr_engine"])

for page in result.get("pages", []):
    print(f"\n--- Page {page['page_number']} ---")
    print(page["text"])