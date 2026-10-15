from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService

class RetrievalService:
    """Retrieve evidence from the unified investigation documents vector store."""

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def retrieve(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:

        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # Step 1: Generate vector embedding for the search query
        query_embeddings = self.embedding_service.create_embeddings([query])
        query_embedding = query_embeddings[0]

        # Step 2: Search the Qdrant collection where ingested files are stored
        points = self.qdrant_service.search(
            query_embedding=query_embedding,
            limit=limit
        )

        retrieved_chunks = []

        for point in points:
            payload = point.payload or {}
            text = payload.get("text", "")
            metadata = payload.get("metadata", {})

            if not text.strip():
                continue

            retrieved_chunks.append({
                "score": point.score,
                "text": text,
                "metadata": metadata
            })

        return retrieved_chunks

    def close(self):
        # Qdrant local client manages connections automatically
        pass