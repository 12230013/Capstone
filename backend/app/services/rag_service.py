import re

from app.services.retrieval_service import RetrievalService
from app.services.prompt_service import PromptService
from app.services.llm_service import LLMService


class RAGService:

    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.prompt_service = PromptService()
        self.llm_service = LLMService()

    def query(
        self,
        query: str,
        limit: int = 3
    ) -> dict:

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # Step 1: Retrieve relevant evidence
        retrieved_chunks = self.retrieval_service.retrieve(
            query=query,
            limit=limit
        )

        # Step 2: Detect whether a specific investigation
        # case was mentioned in the user's query.
        case_match = re.search(
            r"investigation\s+case\s+(\d+)",
            query,
            re.IGNORECASE
        )

        case_number = None

        if case_match:
            case_number = case_match.group(1).zfill(3)

        # Step 3: If a specific case was requested,
        # keep only evidence belonging to that case.
        if case_number:

            target_filename = (
                f"case_{case_number}.txt"
            )

            filtered_chunks = [
                chunk
                for chunk in retrieved_chunks
                if chunk["metadata"].get(
                    "filename",
                    ""
                ).lower() == target_filename.lower()
            ]

            # Only replace the retrieved evidence if
            # matching case evidence was found.
            if filtered_chunks:
                retrieved_chunks = filtered_chunks

        # Step 4: Build prompt using the selected evidence
        prompt = self.prompt_service.build_prompt(
            query=query,
            retrieved_chunks=retrieved_chunks
        )

        # Step 5: Generate answer using Mistral
        answer = self.llm_service.generate(prompt)

        # Step 6: Prepare sources
        sources = []

        for chunk in retrieved_chunks:
            sources.append({
                "filename": chunk["metadata"].get(
                    "filename",
                    "Unknown source"
                ),
                "score": chunk["score"]
            })

        return {
            "answer": answer,
            "sources": sources
        }