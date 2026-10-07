from app.document_processing.text_chunker import chunk_text


text = """
Investigation Case 001

The interview was conducted on 15 August 2026.
The witness stated that the meeting occurred in Thimphu.
The meeting involved three individuals.
The witness provided information about a financial transaction.
The transaction occurred on 20 August 2026.
"""


metadata = {
    "filename": "test.pdf",
    "file_type": "pdf",
    "page_number": 1
}

chunks = chunk_text(
    text,
    chunk_size=150,
    overlap=60,
    metadata=metadata
)

for chunk in chunks:
    print(f"\n--- Chunk {chunk['chunk_id']} ---")
    print("Text:", chunk["text"])
    print("Metadata:", chunk["metadata"])