from app.services.evidence_grounding import answer_document_question, numbered_sentences, NO_INFORMATION
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
import re
import time

class RAGService:

    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService()

    def query(
        self,
        query: str,
        limit: int = 6,
        user_query: str | None = None,
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

        if user_query is None:
            user_query = query

        # ---------------------------------------------------------
        # Step 1: Retrieve relevant evidence
        #
        # RetrievalService now uses LlamaIndex + Qdrant.
        # It also handles investigation-case filtering.
        # ---------------------------------------------------------

        started = time.monotonic()
        print("Document search: retrieving evidence...", flush=True)
        retrieved_chunks = self.retrieval_service.retrieve(
            query=query,
            limit=limit
        )
        print(f"Document search: retrieved {len(retrieved_chunks)} chunks in {time.monotonic() - started:.1f}s", flush=True)

        if not retrieved_chunks:
            return {"answer": NO_INFORMATION, "sources": []}

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

        sentences = {}
        for chunk in retrieved_chunks:
            sentences.update(numbered_sentences(chunk.get("text", "")))
        print("Document search: checking evidence and generating answer...", flush=True)
        context = "\n".join(dict.fromkeys(
            f"{meta.get('doc_id', '')}: statement by {meta.get('person_name', 'Unknown')}, "
            f"case {meta.get('case_no', '')}, dated {meta.get('statement_date', '')}"
            for meta in (chunk.get('metadata', {}).get('metadata', {}) for chunk in retrieved_chunks)
        ))
        grounded = answer_document_question(user_query, sentences, self.llm_service.generate, document_context=context)
        if not grounded["has_information"]:
            return {"answer": grounded["answer"], "sources": []}
        answer = grounded["answer"]

        # ---------------------------------------------------------
        # Step 4: Prepare sources
        # ---------------------------------------------------------
        sources_by_document = {}
        cited = set(grounded["sentence_ids"])
        for chunk in retrieved_chunks:
            metadata = chunk.get("metadata", {}).get("metadata", {})
            chunk_sentences = numbered_sentences(chunk.get("text", ""))
            ids = [key for key in chunk_sentences if key in cited]
            if not ids:
                continue
            doc_id = metadata.get("doc_id", "")
            filename = metadata.get("filename", "Unknown source")
            source = sources_by_document.setdefault(doc_id or filename, {
                "filename": filename, "doc_id": doc_id,
                "case_no": metadata.get("case_no", ""),
                "person_name": metadata.get("person_name", ""),
                "statement_date": metadata.get("statement_date", ""),
                "sentence_ids": [], "excerpt": "",
            })
            for key in ids:
                if key not in source["sentence_ids"]:
                    source["sentence_ids"].append(key)
                    source["excerpt"] += f"[{key}] {sentences[key]}\n"
        sources = list(sources_by_document.values())
        return {
            "answer": answer,
            "sources": sources
        }



    def close(self):
        self.retrieval_service.close()
