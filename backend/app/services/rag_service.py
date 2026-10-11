from app.services.retrieval_service import RetrievalService
from app.services.prompt_service import PromptService
from app.services.llm_service import LLMService
import re

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

        # ---------------------------------------------------------
        # Validate input
        # ---------------------------------------------------------

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # ---------------------------------------------------------
        # Step 1: Retrieve relevant evidence
        #
        # RetrievalService now uses LlamaIndex + Qdrant.
        # It also handles investigation-case filtering.
        # ---------------------------------------------------------

        retrieved_chunks = self.retrieval_service.retrieve(
            query=query,
            limit=limit
        )

        # ---------------------------------------------------------
        # Detect whether the query specifies an investigation case
        # ---------------------------------------------------------

        case_match = re.search(
            r"investigation\s+case\s+(\d+)",
            query,
            re.IGNORECASE
        )

        case_number = None

        if case_match:
            case_number = case_match.group(1).zfill(3)

        # ---------------------------------------------------------
        # If no case is specified and multiple cases were retrieved,
        # ask the user to specify the case.
        # ---------------------------------------------------------

        if case_number is None:

            case_numbers = set()

            for chunk in retrieved_chunks:

                metadata = chunk.get("metadata", {})
                file_metadata = metadata.get("metadata", {})

                case_no = file_metadata.get("case_no", "")
                if case_no:
                    case_numbers.add(case_no)

            if len(case_numbers) > 1:

                cases = ", ".join(
                    sorted(case_numbers)
            )

                return {
                    "answer": (
                        "Your question is ambiguous because the "
                        "available evidence relates to multiple "
                        f"investigation cases ({cases}). "
                        "Please specify the investigation case "
                        "you are referring to."
                    ),
                    "sources": []
                }

        # ---------------------------------------------------------
        # Step 2: Build prompt using retrieved evidence
        # ---------------------------------------------------------

        prompt = self.prompt_service.build_prompt(
            query=query,
            retrieved_chunks=retrieved_chunks
        )

        # ---------------------------------------------------------
        # Step 3: Generate answer using local Mistral
        # ---------------------------------------------------------

        answer = self.llm_service.generate(prompt)

        # ---------------------------------------------------------
        # Step 4: Prepare sources
        # ---------------------------------------------------------
        sources = []
        seen_sources = set()

        for chunk in retrieved_chunks:
            metadata = chunk.get("metadata", {})
            file_metadata = metadata.get("metadata", {})

            doc_id = file_metadata.get("doc_id", "")
            filename = file_metadata.get("filename", "Unknown source")

            # Identify each file uniquely
            source_key = doc_id or filename
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            sources.append({
                    "filename": filename,
                    "doc_id": doc_id,
                    "case_no": file_metadata.get("case_no", ""),
                    "person_name": file_metadata.get("person_name", ""),
                    "statement_date": file_metadata.get("statement_date", ""),
                    "sentence_ids": file_metadata.get("sentence_ids", []),
                    "excerpt": chunk.get("text", ""),
            })
        return {
            "answer": answer,
            "sources": sources
        }



    def close(self):
        self.retrieval_service.close()
