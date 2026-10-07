from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService

embedding_service = EmbeddingService()
qdrant_service = QdrantService()

text = (
    "The witness stated that the meeting "
    "occurred in Thimphu."
)

metadata = {
    "filename": "test.pdf",
    "file_type": "pdf",
    "page_number": 1
}

embedding = embedding_service.create_embedding(text)

qdrant_service.add_chunk(
    chunk_id=1,
    text=text,
    embedding=embedding,
    metadata=metadata
)

print("Chunk successfully stored in Qdrant.")

points = qdrant_service.client.retrieve(
    collection_name=qdrant_service.collection_name,
    ids=[1],
    with_vectors=True
)

print("\nRetrieved points:")
print(points)

qdrant_service.client.close()