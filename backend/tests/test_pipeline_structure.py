"""Structural branch tests for real routing, retrieval, grounding, and document utilities."""
import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Replace the external vector/embedding client while importing real service logic.
index = types.ModuleType("acc_statements.index")
index.search = MagicMock(return_value=[])
index.close_client = MagicMock()
with patch.dict(sys.modules, {"acc_statements.index": index}):
    services = importlib.import_module("app.services.chat_service")
    RealChatService = services.ChatService
    RealRagService = importlib.import_module("app.services.rag_service").RAGService
    RealRetrievalService = importlib.import_module("app.services.retrieval_service").RetrievalService
from app.services.evidence_grounding import NO_INFORMATION
from app.document_processing.text_chunker import chunk_text
from app.document_processing.text_cleaner import clean_text
from app.document_processing.document_loader import load_document


class RouterBranchTests(unittest.TestCase):
    def setUp(self):
        self.service = RealChatService()
        self.service._rag_service = MagicMock()
        self.service._rag_service.query.return_value = {"answer": "Supported", "sources": []}
        self.service._statement_service = MagicMock()

    def ask(self, question, context=None):
        return asyncio.run(self.service.query(question, context=context))

    def test_empty_and_nontext_queries_are_rejected(self):
        for query in ("", "  ", None):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.ask(query)

    def test_general_document_question_uses_rag(self):
        response = self.ask("Who owns the demonstration sawmill?")
        self.assertEqual(response["response"]["answer"], "Supported")
        self.service._rag_service.query.assert_called_once()

    def test_phone_and_citizen_ids_route_to_different_systems(self):
        self.service._handle_cdr_query = AsyncMock(return_value={"response": {"answer": "CDR"}})
        self.service._handle_relationship_query = AsyncMock(return_value={"response": {"answer": "Family"}})
        self.assertEqual(self.ask("Analyze calls for 17123456")["response"]["answer"], "CDR")
        self.assertEqual(self.ask("Show family for 10808000040")["response"]["answer"], "Family")
        self.assertEqual(self.service._handle_cdr_query.call_args.args[-1], "17123456")
        self.assertEqual(self.service._handle_relationship_query.call_args.args[-1], "10808000040")

    def test_incomplete_cdr_query_requests_identifier_without_document_generation(self):
        response = self.ask("Analyze the call records")
        self.assertIn("8-digit", response["response"]["answer"])
        self.service._rag_service.query.assert_not_called()

    def test_multi_system_question_uses_combined_evidence(self):
        self.service._handle_combined_query = AsyncMock(return_value={"response": {"answer": "Combined"}})
        self.assertEqual(self.ask("Compare witness statements and call records")["response"]["answer"], "Combined")
        self.service._handle_combined_query.assert_awaited_once()

    def test_statement_listing_phrases_use_the_document_inventory(self):
        self.service._statement_service.list_statements.return_value = [{
            "statement_id": "synthetic", "name": "Synthetic Witness",
        }]
        for question in ("show statements", "list all the statements"):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertIn("Found 1 statement document", response["response"]["answer"])
        self.service._rag_service.query.assert_not_called()

    def test_document_context_skips_current_and_assistant_messages(self):
        context = {"current_query": "Current", "messages": [
            {"role": "user", "content": "Earlier case"}, {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Current"},
        ]}
        self.assertEqual(self.service._get_document_context(context), "Earlier case")
        self.assertIsNone(self.service._get_document_context({}))

    def test_identifier_context_uses_most_recent_values(self):
        values = self.service._get_context_identifiers({"messages": [
            {"content": "Old 17111111"}, {"content": "New 17222222 and CID 10808000040"},
        ]})
        self.assertEqual(values, {"phone_number": "17222222", "cid": "10808000040"})


class RagBranchTests(unittest.TestCase):
    def setUp(self):
        self.rag = RealRagService()
        self.rag.retrieval_service = MagicMock()
        self.rag.llm_service = MagicMock()
        self.chunk = {"text": "[stmt_01-s1] Pema owns the sawmill.", "metadata": {"metadata": {
            "doc_id": "stmt_01", "filename": "stmt_01.txt", "case_no": "19/25-26", "sentence_ids": ["stmt_01-s1"],
        }}}

    def generated(self, has_information=True):
        return json.dumps({"has_information": has_information, "claims": [{
            "statement": "Pema owns the sawmill.", "evidence": [{"sentence_id": "stmt_01-s1", "quote": "Pema owns the sawmill."}],
        }] if has_information else [], "missing_information": []})

    def test_invalid_rag_inputs_are_rejected(self):
        for query, limit in ((None, 3), ("", 3), ("Question", 0)):
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                self.rag.query(query, limit=limit)

    def test_no_retrieved_evidence_skips_model(self):
        self.rag.retrieval_service.retrieve.return_value = []
        self.assertEqual(self.rag.query("Unknown")['answer'], NO_INFORMATION)
        self.rag.llm_service.generate.assert_not_called()

    def test_supported_answer_includes_only_verified_sources(self):
        self.rag.retrieval_service.retrieve.return_value = [self.chunk]
        self.rag.llm_service.generate.return_value = self.generated()
        response = self.rag.query("Who owns the sawmill?")
        self.assertIn("[stmt_01-s1]", response["answer"])
        self.assertEqual(response["sources"][0]["sentence_ids"], ["stmt_01-s1"])

    def test_missing_fact_in_retrieved_documents_returns_no_information(self):
        self.rag.retrieval_service.retrieve.return_value = [self.chunk]
        self.rag.llm_service.generate.return_value = self.generated(False)
        self.assertEqual(self.rag.query("What is the salary?"), {"answer": NO_INFORMATION, "sources": []})

    def test_ambiguous_cases_request_clarification_before_generation(self):
        other = {"text": "[stmt_02-s1] Another case.", "metadata": {"metadata": {"case_no": "20/25-26"}}}
        self.rag.retrieval_service.retrieve.return_value = [self.chunk, other]
        self.assertIn("Please specify", self.rag.query("Summarize the evidence")["answer"])
        self.rag.llm_service.generate.assert_not_called()

    def test_exact_case_identifier_is_forwarded_to_vector_search(self):
        index.search.reset_mock()
        index.search.return_value = []
        RealRetrievalService().retrieve("Show case 19/25-26")
        self.assertEqual(index.search.call_args.kwargs["case_nos"], ["19/25-26"])


class DocumentBranchTests(unittest.TestCase):
    def test_cleaning_normalizes_spaces_and_blank_lines(self):
        self.assertEqual(clean_text("  First\t line \n\n\n Second line  "), "First line\n\nSecond line")
        with self.assertRaises(ValueError):
            clean_text(None)

    def test_chunking_preserves_sentences_and_copies_metadata(self):
        metadata = {"filename": "synthetic.txt"}
        chunks = chunk_text("One sentence. Two sentences. Three sentences.", chunk_size=30, overlap=15, metadata=metadata)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["metadata"], metadata)
        chunks[0]["metadata"]["filename"] = "changed"
        self.assertEqual(metadata["filename"], "synthetic.txt")
        self.assertTrue(any("Three sentences." in chunk["text"] for chunk in chunks))

    def test_chunking_rejects_invalid_configuration_and_handles_empty_text(self):
        for options in ({"chunk_size": 0}, {"overlap": -1}, {"chunk_size": 10, "overlap": 10}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                chunk_text("Text", **options)
        with self.assertRaises(ValueError):
            chunk_text(None)
        self.assertEqual(chunk_text(" "), [])

    def test_text_loader_and_missing_or_unsupported_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "synthetic.txt"
            file.write_text("Synthetic source sentence.", encoding="utf-8")
            self.assertEqual(load_document(str(file))["text"], "Synthetic source sentence.")
            with self.assertRaises(FileNotFoundError):
                load_document(str(root / "missing.txt"))
            unsupported = root / "unsupported.bin"
            unsupported.write_bytes(b"data")
            with self.assertRaises(ValueError):
                load_document(str(unsupported))
