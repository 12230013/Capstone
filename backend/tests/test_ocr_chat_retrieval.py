import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.ocr.chat_retrieval import (
    OCRChatRetrievalService,
    extract_document_filename,
    extract_pdf_filename,
)


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeDocumentsCollection:
    def __init__(self, documents):
        self.documents = documents
        self.find_calls = []

    def find(self, query, projection):
        self.find_calls.append((query, projection))
        matches = [
            document
            for document in self.documents
            if all(document.get(key) == value for key, value in query.items())
        ]
        return FakeCursor(matches)


class FakeOCRAdapter:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error
        self.retrieve_calls = []

    def retrieve_document(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        if self.error:
            raise self.error
        return self.chunks


def indexed_document(
    document_id="owned-document",
    filename="owned.pdf",
    owner_user_id="user-1",
    index_status="indexed",
):
    return {
        "_id": document_id,
        "filename": filename,
        "owner_user_id": owner_user_id,
        "status": "completed",
        "ocr_status": "completed",
        "index_status": index_status,
    }


class OCRFilenameRoutingTests(unittest.TestCase):
    def test_extracts_supported_document_filenames_and_rejects_ambiguous_requests(self):
        self.assertEqual(
            extract_document_filename("Summarize C:\\uploads\\statement_04.pdf."),
            "statement_04.pdf",
        )
        self.assertEqual(
            extract_document_filename('Read "annual report.pdf"'),
            "annual report.pdf",
        )
        for filename in (
            "statement_01.jpeg",
            "statement_01.jpg",
            "statement_01.png",
        ):
            with self.subTest(filename=filename):
                self.assertEqual(
                    extract_document_filename(f"Summarize {filename}"),
                    filename,
                )
        self.assertEqual(
            extract_pdf_filename("Summarize statement_01.jpeg"),
            "statement_01.jpeg",
        )
        self.assertIsNone(
            extract_document_filename("Summarize the transaction.")
        )
        with self.assertRaises(HTTPException) as raised:
            extract_document_filename("Compare a.pdf with b.jpeg")
        self.assertEqual(raised.exception.status_code, 400)
        with self.assertRaises(HTTPException) as raised:
            extract_document_filename('Compare "a.pdf" with b.jpeg')
        self.assertEqual(raised.exception.status_code, 400)


class OCRChatRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.documents = FakeDocumentsCollection([indexed_document()])
        self.adapter = FakeOCRAdapter(
            chunks=[
                {
                    "text": "Transfer appears on this page.",
                    "score": 0.9,
                    "metadata": {
                        "metadata": {
                            "document_id": "owned-document",
                            "doc_id": "owned-point",
                            "owner_user_id": "user-1",
                            "filename": "owned.pdf",
                            "page_number": 3,
                            "chunk_id": "p3-c1",
                        }
                    },
                }
            ]
        )
        self.service = OCRChatRetrievalService(
            documents_collection=self.documents,
            adapter_factory=lambda: self.adapter,
        )

    def test_owned_exact_filename_retrieval_preserves_page_citation(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value=(
                "The note says [sic], [item 1], and [see appendix]. "
                "The transfer appears on [owned.pdf, page 3] "
                "[owned.pdf, page 3]."
            ),
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertEqual(
            self.documents.find_calls[0][0],
            {"filename": "owned.pdf", "owner_user_id": "user-1"},
        )
        self.assertEqual(
            self.adapter.retrieve_calls,
            [
                {
                    "query": "Summarize owned.pdf",
                    "document_id": "owned-document",
                    "owner_user_id": "user-1",
                }
            ],
        )
        self.assertIn("[owned.pdf, page 3]", response["answer"])
        self.assertIn("[sic]", response["answer"])
        self.assertIn("[item 1]", response["answer"])
        self.assertIn("[see appendix]", response["answer"])
        self.assertEqual(response["warnings"], [])
        self.assertEqual(response["sources"][0]["filename"], "owned.pdf")
        self.assertEqual(response["sources"][0]["page_number"], 3)
        self.assertEqual(
            response["sources"][0]["excerpt"],
            "Transfer appears on this page.",
        )
        self.assertEqual(response["sources"][0]["chunk_ids"], ["p3-c1"])

    def test_plain_filename_mention_is_not_treated_as_a_citation(self):
        answer = "The document owned.pdf contains a transfer."
        with patch("app.services.llm_service.LLMService.generate", return_value=answer):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertEqual(response["answer"], answer)
        self.assertEqual(response["warnings"], [])
        self.assertEqual(response["sources"][0]["filename"], "owned.pdf")

    def test_filename_punctuation_and_multiple_retrieved_documents_are_supported(self):
        chunks = [
            self.adapter.chunks[0],
            {
                "text": "Year-end audit evidence.",
                "metadata": {
                    "metadata": {
                        "document_id": "second-document",
                        "doc_id": "second-point",
                        "owner_user_id": "user-1",
                        "filename": "year_end,[audit]-2026.v2-final.pdf",
                        "page_number": 12,
                        "chunk_id": "p12-c4",
                        "confidence": 98.0,
                    }
                },
            },
        ]
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value=(
                "The transfer is shown [owned.pdf, page 3]. "
                "The audit appears [year_end,[audit]-2026.v2-final.pdf, page 12]."
            ),
        ):
            response = OCRChatRetrievalService._build_answer(
                "Compare the OCR evidence.", chunks
            )

        self.assertEqual(response["warnings"], [])
        self.assertIn(
            "[year_end,[audit]-2026.v2-final.pdf, page 12]",
            response["answer"],
        )
        self.assertEqual(
            [source["filename"] for source in response["sources"]],
            ["owned.pdf", "year_end,[audit]-2026.v2-final.pdf"],
        )
        self.assertEqual(response["sources"][1]["page_number"], 12)
        self.assertEqual(response["sources"][1]["chunk_ids"], ["p12-c4"])
        self.assertEqual(
            response["sources"][1]["excerpts"][0]["ocr_metadata"]["confidence"],
            98.0,
        )

    def test_statement_style_citation_fails_closed_and_preserves_sources(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value="The transfer is confirmed [stmt_01-s4].",
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertNotIn("[stmt_01-s4]", response["answer"])
        self.assertIn(
            "could not provide an answer",
            response["answer"],
        )
        self.assertTrue(response["warnings"])
        self.assertEqual(response["sources"][0]["filename"], "owned.pdf")
        self.assertEqual(response["sources"][0]["page_number"], 3)
        self.assertEqual(response["sources"][0]["chunk_ids"], ["p3-c1"])
        self.assertEqual(
            response["sources"][0]["excerpts"][0]["ocr_metadata"]["chunk_id"],
            "p3-c1",
        )

    def test_unretrieved_page_citation_fails_closed(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value="The transfer is confirmed [owned.pdf, page 2].",
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertNotIn("[owned.pdf, page 2]", response["answer"])
        self.assertTrue(response["warnings"])
        self.assertEqual(response["sources"][0]["page_number"], 3)

    def test_unbracketed_unretrieved_filename_page_reference_fails_closed(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value="The transfer appears in owned.pdf, page 2.",
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertNotIn("owned.pdf, page 2", response["answer"])
        self.assertIn("could not provide an answer", response["answer"])
        self.assertTrue(response["warnings"])
        self.assertEqual(response["sources"][0]["page_number"], 3)

    def test_malformed_pdf_page_citation_fails_closed(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value="The transfer appears in [owned.pdf page two].",
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertNotIn("[owned.pdf page two]", response["answer"])
        self.assertTrue(response["warnings"])
        self.assertEqual(response["sources"][0]["filename"], "owned.pdf")

    def test_empty_and_whitespace_model_responses_fail_closed(self):
        for model_answer in ("", " \n\t"):
            with self.subTest(model_answer=repr(model_answer)):
                with patch(
                    "app.services.llm_service.LLMService.generate",
                    return_value=model_answer,
                ):
                    response = self.service.retrieve(
                        query="Summarize owned.pdf",
                        filename="owned.pdf",
                        owner_user_id="user-1",
                    )

                self.assertIn("empty response", response["answer"])
                self.assertTrue(response["warnings"])
                self.assertIn(
                    "empty answer",
                    response["warnings"][0],
                )
                self.assertEqual(
                    response["sources"][0]["filename"],
                    "owned.pdf",
                )
                self.assertEqual(response["sources"][0]["page_number"], 3)

    def test_different_document_citation_fails_closed(self):
        with patch(
            "app.services.llm_service.LLMService.generate",
            return_value=(
                "The transfer is shown [owned.pdf, page 3]. "
                "Unsupported evidence [other.pdf, page 3]."
            ),
        ):
            response = self.service.retrieve(
                query="Summarize owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertNotIn("[owned.pdf, page 3]", response["answer"])
        self.assertNotIn("[other.pdf, page 3]", response["answer"])
        self.assertTrue(response["warnings"])
        self.assertEqual(
            [source["filename"] for source in response["sources"]],
            ["owned.pdf"],
        )

    def test_another_users_document_is_not_resolved_or_retrieved(self):
        self.documents.documents = [
            indexed_document(
                document_id="foreign-document",
                owner_user_id="user-2",
            )
        ]

        response = self.service.retrieve(
            query="Read owned.pdf",
            filename="owned.pdf",
            owner_user_id="user-1",
        )

        self.assertIsNone(response)
        self.assertEqual(
            self.documents.find_calls[0][0],
            {"filename": "owned.pdf", "owner_user_id": "user-1"},
        )
        self.assertEqual(self.adapter.retrieve_calls, [])

    def test_duplicate_owned_filenames_are_rejected(self):
        self.documents.documents.append(
            indexed_document(document_id="second-document")
        )

        with self.assertRaises(HTTPException) as raised:
            self.service.retrieve(
                query="Read owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.adapter.retrieve_calls, [])

    def test_owned_but_unindexed_document_is_rejected(self):
        self.documents.documents[0]["index_status"] = "indexing"

        with self.assertRaises(HTTPException) as raised:
            self.service.retrieve(
                query="Read owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.adapter.retrieve_calls, [])

    def test_qdrant_failure_is_reported_as_unavailable(self):
        self.adapter.error = RuntimeError("private qdrant detail")

        with self.assertRaises(HTTPException) as raised:
            self.service.retrieve(
                query="Read owned.pdf",
                filename="owned.pdf",
                owner_user_id="user-1",
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertNotIn("private qdrant detail", raised.exception.detail)

    def test_empty_ocr_retrieval_is_an_explicit_no_evidence_response(self):
        self.adapter.chunks = []
        answer_builder = Mock()
        service = OCRChatRetrievalService(
            documents_collection=self.documents,
            adapter_factory=lambda: self.adapter,
            answer_builder=answer_builder,
        )

        response = service.retrieve(
            query="Read owned.pdf",
            filename="owned.pdf",
            owner_user_id="user-1",
        )

        self.assertIn("No OCR chunks", response["answer"])
        self.assertEqual(response["sources"], [])
        self.assertTrue(response["warnings"])
        answer_builder.assert_not_called()

    def test_missing_metadata_collection_is_reported(self):
        with patch("app.ocr.chat_retrieval.ocr_documents_collection", None):
            service = OCRChatRetrievalService()
            with self.assertRaises(HTTPException) as raised:
                service.retrieve(
                    query="Read owned.pdf",
                    filename="owned.pdf",
                    owner_user_id="user-1",
                )
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
