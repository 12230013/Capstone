
import re

from acc_statements.index import search as search_statements
from acc_statements.index import close_client


class RetrievalService:
    """Retrieve evidence from the existing ACC statements index."""

    def retrieve(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:

        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # Filter by the exact case identifier when one is supplied.
        case_match = re.search(
            r"\bACC/\d{4}/\d{3}\b",
            query,
            re.IGNORECASE
        )

        case_nos = (
            [case_match.group(0).upper()]
            if case_match
            else None
        )

        # Search the existing BGE-M3/Qdrant index.
        results = search_statements(
            query=query,
            case_nos=case_nos,
            top_k=limit
        )

        retrieved_chunks = []

        for result in results:
            doc_id = result.get("doc_id", "unknown")
            filename = f"{doc_id}.txt"

            # The existing index stores numbered sentence text here.
            text = result.get("text_numbered", "")

            if not text.strip():
                continue

            retrieved_chunks.append({
                "score": result.get("score", 0.0),
                "text": text,
                "metadata": {
                    "metadata": {
                        "filename": filename,
                        "case_no": result.get("case_no", ""),
                        "doc_id": doc_id,
                        "person_name": result.get("person_name", ""),
                        "statement_date": result.get(
                            "statement_date", ""
                        ),
                        "sentence_ids": result.get(
                            "sentence_ids", []
                        )
                    }
                }
            })

        return retrieved_chunks

    def close(self):
        close_client()
