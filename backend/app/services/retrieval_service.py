import re

from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService


class RetrievalService:

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def retrieve(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # Step 1: Detect investigation case from the query
        case_match = re.search(
            r"investigation\s+case\s+(\d+)",
            query,
            re.IGNORECASE
        )

        case_number = None

        if case_match:
            case_number = case_match.group(1).zfill(3)

        # Step 2: Create query embedding
        query_embedding = self.embedding_service.create_embedding(
            query
        )

        # Step 3: Retrieve more results than needed
        # so we can prioritize the requested case.
        search_limit = max(limit * 3, 10)

        results = self.qdrant_service.search(
            query_embedding=query_embedding,
            limit=search_limit
        )

        # Step 4: Convert Qdrant results
        retrieved_chunks = []

        for result in results:

            metadata = result.payload.get(
                "metadata",
                {}
            )

            filename = metadata.get(
                "filename",
                ""
            )

            retrieved_chunks.append({
                "score": result.score,
                "text": result.payload.get(
                    "text",
                    ""
                ),
                "metadata": metadata,
                "_filename": filename
            })

        # Step 5: If a case was specified,
        # prioritize documents belonging to that case.
        if case_number:

            target_filename = (
                f"case_{case_number}.txt"
            )

            retrieved_chunks.sort(
                key=lambda item: (
                    item["_filename"].lower()
                    != target_filename.lower(),
                    -item["score"]
                )
            )

        else:

            # No specific case was mentioned.
            # Keep normal similarity ranking.
            retrieved_chunks.sort(
                key=lambda item: -item["score"]
            )

        # Step 6: Remove internal helper field
        for chunk in retrieved_chunks:
            chunk.pop("_filename", None)

        # Step 7: Return only the requested number
        return retrieved_chunks[:limit]