from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService

embedding_service = EmbeddingService()
qdrant_service = QdrantService()

question = (
    "Where did the witness say the meeting took place?"
)

query_embedding = embedding_service.create_embedding(
    question
)

results = qdrant_service.search(
    query_embedding=query_embedding,
    limit=3
)

print("\nSearch results:")

for result in results:
    print("\nScore:", result.score)
    print("Text:", result.payload["text"])
    print("Metadata:", result.payload["metadata"])

qdrant_service.client.close()