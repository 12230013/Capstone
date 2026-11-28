"""Synthetic tests for fail-closed CIMS authorization and document publication."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException

from app.services import cims_documents, cims_service


class CaseAccessTests(unittest.TestCase):
    session = {"user_id": "synthetic-account"}

    def test_missing_grant_stops_before_assignment_read(self):
        database = MagicMock()
        database.__getitem__.return_value.find_one.return_value = None
        with patch.object(cims_service.connection, "db", database), patch.object(
            cims_service.connection, "cims_sync_collection"
        ) as batches:
            with self.assertRaises(HTTPException) as denied:
                cims_service.read_case(self.session, "case-a", ("interviews",))
            self.assertEqual(denied.exception.status_code, 403)
            batches.aggregate.assert_not_called()

    def test_wrong_assignment_stops_before_protected_fields(self):
        revision = {"investigators": ["different-investigator"]}
        with patch.object(cims_service, "_grant", return_value="investigator-a"), patch.object(
            cims_service, "_current_assignment", return_value=revision
        ), patch.object(cims_service, "read_case_fields") as read:
            with self.assertRaises(HTTPException):
                cims_service.read_case(self.session, "case-a", ("interviews",))
            read.assert_not_called()

    def test_duplicate_case_revision_is_accepted_but_conflict_is_denied(self):
        first = {"revision": "2026-11-20", "fingerprint": "same", "position": 0}
        batches = MagicMock()
        with patch.object(cims_service.connection, "cims_sync_collection", batches):
            batches.aggregate.return_value = [first, dict(first)]
            self.assertEqual(cims_service._current_assignment("case-a"), first)
            batches.aggregate.return_value = [first, {**first, "fingerprint": "different"}]
            self.assertIsNone(cims_service._current_assignment("case-a"))

    def test_document_access_requires_permission_before_manifest_read(self):
        with patch.object(
            cims_documents, "authorize_case", side_effect=HTTPException(403)
        ) as authorize, patch.object(cims_documents, "manifests") as manifests:
            with self.assertRaises(HTTPException):
                cims_documents._published_versions(self.session, "case-a")
            authorize.assert_called_once_with(self.session, "case-a", cims_service.DOCUMENT_READ)
            manifests.assert_not_called()

    def test_null_interview_statement_is_unavailable(self):
        data = {"interviews": [{"interview_id": "test-interview", "statement_text": None}]}
        with patch.object(cims_service, "read_case", return_value=data):
            answer = cims_service.answer_case_query(self.session, "case-a", "Interview statement")
        self.assertIn("statement text: Unavailable", answer["response"]["answer"])


class DocumentSyncTests(unittest.TestCase):
    def test_extensionless_docx_extracts_paragraphs_and_tables(self):
        from tempfile import TemporaryDirectory
        from docx import Document

        with TemporaryDirectory() as directory:
            document = Document()
            document.add_paragraph("Synthetic paragraph")
            document.add_table(rows=1, cols=1).cell(0, 0).text = "Synthetic table cell"
            path = Path(directory) / "extensionless"
            document.save(path)
            self.assertEqual(cims_documents._units(path, "synthetic"), [
                (1, "Synthetic paragraph"), (2, "Synthetic table cell"),
            ])

    def test_reconciliation_waits_for_a_stable_matching_file_and_ignores_symlinks(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case-a"
            case.mkdir()
            (case / "doc-a_summary").write_bytes(b"synthetic")
            (case / "unmatched").write_bytes(b"synthetic")
            (case / "doc-b_other").symlink_to(case / "doc-a_summary")
            metadata = [
                {"document_id": "doc-a", "file_name": "summary.pdf"},
                {"document_id": "doc-b", "file_name": "other.pdf"},
            ]
            with patch.object(cims_documents, "_documents", return_value=metadata), patch.object(
                cims_documents, "manifests"
            ) as manifests, patch.object(cims_documents, "_index") as index:
                observed = cims_documents.reconcile(root, {})
                index.assert_not_called()
                cims_documents.reconcile(root, observed)
                index.assert_called_once()
                self.assertEqual(index.call_args.args[:2], ("case-a", "doc-a"))
                self.assertEqual(
                    manifests.return_value.update_one.call_args.args[1]["$set"]["status"],
                    "pending_metadata",
                )

    def test_qdrant_returns_only_the_authorized_published_version(self):
        from uuid import uuid4

        from qdrant_client import QdrantClient, models
        from acc_statements import index

        client = QdrantClient(":memory:")
        self.addCleanup(client.close)
        client.create_collection(cims_documents.COLLECTION, vectors_config=models.VectorParams(
            size=2, distance=models.Distance.COSINE,
        ))
        points = [
            models.PointStruct(id=str(uuid4()), vector=[1.0, 0.0], payload={
                "case_id": case_id, "version": version, "text": text,
            })
            for case_id, version, text in [
                ("case-a", "published", "visible"),
                ("case-a", "unpublished", "staged"),
                ("case-b", "published", "different case"),
            ]
        ]
        client.upsert(cims_documents.COLLECTION, points=points)
        with patch.object(cims_documents, "_published_versions", return_value=["published"]), patch.object(
            index, "get_client", return_value=client
        ), patch.object(index, "embed", return_value=[[1.0, 0.0]]):
            hits = cims_documents.search_case_documents({}, "case-a", "synthetic")
            self.assertEqual([point["text"] for point in hits], ["visible"])
            self.assertEqual(cims_documents.read_source_excerpt({}, "case-a", points[0].id)["text"], "visible")
            for point in points[1:]:
                with self.assertRaises(HTTPException) as denied:
                    cims_documents.read_source_excerpt({}, "case-a", point.id)
                self.assertEqual(denied.exception.status_code, 404)

    def test_document_history_stays_within_published_versions(self):
        with patch.object(cims_documents, "_published_versions", return_value=["current"]) as versions:
            scope = cims_documents.conversation_message_scope(
                {"user_id": "synthetic"}, {"case_id": "case-a", "case_mode": "documents"},
            )
        versions.assert_called_once_with({"user_id": "synthetic"}, "case-a")
        self.assertEqual(scope, {"source_versions": {"$not": {"$elemMatch": {"$nin": ["current"]}}}})

    def test_extensionless_pdf_uses_existing_ocr_entry_point(self):
        from tempfile import TemporaryDirectory
        from app.ocr import document_ocr

        with TemporaryDirectory() as directory:
            path = Path(directory) / "extensionless"
            path.write_bytes(b"%PDF-synthetic")
            with patch.object(document_ocr, "run_document_ocr", return_value={
                "pages": [{"page_number": 1, "text": "Synthetic text"}],
            }) as extract:
                self.assertEqual(cims_documents._units(path, "synthetic"), [(1, "Synthetic text")])
                extract.assert_called_once_with(str(path), "synthetic", "document.pdf", "application/pdf")


class CaseReferenceTests(unittest.TestCase):
    def test_natural_language_resolves_case_number_to_authorized_case_id(self):
        with patch.object(cims_service, "list_cases", return_value=[
            {"case_id": "canonical-a", "case_number": "67"},
        ]):
            self.assertEqual(
                cims_service.resolve_case_reference({}, "Can you tell me about case 67?"),
                "canonical-a",
            )
            with self.assertRaises(HTTPException) as denied:
                cims_service.resolve_case_reference({}, "What happened in case 68?")
            self.assertEqual(denied.exception.status_code, 403)


class PresentationAccessTests(unittest.TestCase):
    def test_haa_account_can_use_haa_and_tools_but_cannot_open_another_case(self):
        from app.services.presentation_access import HAA_SCOPE, TOOL_SCOPE, presentation_request

        session = {"presentation_access": {"case_id": HAA_SCOPE, "tools": ["cdr", "relationships"]}}
        self.assertEqual(presentation_request(session, "What is the HAA case?", None), (HAA_SCOPE, "metadata", None))
        self.assertEqual(presentation_request(session, "CDR for 00000000", None), (TOOL_SCOPE, "cdr", "00000000"))
        with self.assertRaises(HTTPException):
            cims_service.authorize_conversation_scope(session, {"case_id": "different-case"})

    def test_same_day_receipt_tiebreak_requires_matching_assignments(self):
        first = {"revision": "2026-11-20", "fingerprint": "first", "received_at": 1, "investigators": ["a"]}
        latest = {**first, "fingerprint": "second", "received_at": 2}
        batches = MagicMock()
        with patch.object(cims_service.connection, "cims_sync_collection", batches):
            batches.aggregate.return_value = [latest, first]
            self.assertEqual(cims_service._current_assignment("case-a"), latest)
            batches.aggregate.return_value = [{**latest, "investigators": ["b"]}, first]
            self.assertIsNone(cims_service._current_assignment("case-a"))


class CaseQuestionTests(unittest.TestCase):
    def test_summary_followup_includes_allegations_and_events(self):
        with patch.object(cims_service, "read_case", return_value={
            "allegation_details": "Synthetic allegation",
            "case_events": [{"event_name": "Synthetic event"}],
        }) as read:
            result = cims_service.answer_case_query({}, "case-a", "summarize it")
        read.assert_called_once_with({}, "case-a", cims_service.CASE_OVERVIEW_FIELDS)
        self.assertIn("Synthetic allegation", result["response"]["answer"])
        self.assertIn("Synthetic event", result["response"]["answer"])

    def test_involvement_followup_selects_entities_without_private_identifiers(self):
        with patch.object(cims_service, "read_case", return_value={
            "entities": [{"name": "Example person", "involvement": "Witness", "cid": "private"}],
        }) as read:
            result = cims_service.answer_case_query({}, "case-a", "who are involved in it")
        read.assert_called_once_with({}, "case-a", ("entities",))
        self.assertIn("Example person — Witness", result["response"]["answer"])
        self.assertNotIn("private", result["response"]["answer"])


class CaseRagRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_case_question_uses_both_authorized_sources(self):
        from app.services import chat_service

        session = {"user_id": "synthetic"}
        hit = {"text": "Synthetic evidence", "point_id": "point", "locator": 1, "version": "published"}
        with patch.object(cims_documents, "search_case_documents", return_value=[hit]) as search, patch.object(
            chat_service, "answer_from_evidence", return_value={"answer": "Grounded answer", "sentence_ids": ["cims-record-s1", "cims-s1"]},
        ) as generate, patch.object(cims_service, "case_metadata_passages", return_value={"status": "Open"}) as metadata:
            result = await chat_service.ChatService().query(
                "Tell me about case 67", {"session": session, "case_id": "67", "case_mode": "metadata"},
            )
        search.assert_called_once_with(session, "67", "Tell me about case 67")
        metadata.assert_called_once_with(session, "67", "Tell me about case 67")
        self.assertEqual(generate.call_args.args[1], {"cims-record-s1": "Open", "cims-s1": "Synthetic evidence"})
        self.assertFalse(generate.call_args.kwargs["include_missing_information"])
        self.assertEqual(result["response"]["answer"], "Grounded answer")
        self.assertEqual(result["response"]["sources"][1]["version"], "published")

    async def test_ordinary_case_question_handles_absent_evidence(self):
        from app.services import chat_service

        session = {"user_id": "synthetic"}
        with patch.object(cims_documents, "search_case_documents", return_value=[]), patch.object(
            cims_service, "case_metadata_passages", return_value={},
        ) as metadata, patch.object(chat_service, "answer_from_evidence") as model:
            result = await chat_service.ChatService().query(
                "Summarize it", {"session": session, "case_id": "67", "case_mode": "metadata"},
            )
        metadata.assert_called_once()
        model.assert_not_called()
        self.assertIn("no available case evidence", result["response"]["answer"])


class CaseScanIsolationTests(unittest.TestCase):
    def test_an_unreadable_sibling_does_not_discard_readable_case_observations(self):
        from contextlib import contextmanager
        from tempfile import TemporaryDirectory

        real_open = cims_documents._open_directory

        @contextmanager
        def open_directory(path, parent=None):
            if path == "restricted":
                raise PermissionError()
            with real_open(path, parent) as descriptor:
                yield descriptor

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "restricted").mkdir()
            (root / "67").mkdir()
            (root / "67" / "sample").touch()
            with patch.object(cims_documents, "_open_directory", open_directory), patch.object(
                cims_documents, "_documents", return_value=[{"document_id": "sample", "file_name": "sample.pdf"}]
            ), patch.object(cims_documents, "manifests"):
                (root / "67" / "sample").rename(root / "67" / "sample_report")
                observed = cims_documents.reconcile(root, {})
        self.assertIn(("67", "sample_report"), observed)


class CasePresentationTests(unittest.TestCase):
    def test_titles_distinguish_overview_report_and_timeline(self):
        from app.api.routes.chat import case_conversation_title

        self.assertEqual(case_conversation_title("67", "metadata", "Tell me about case 67"), "Case 67 · Overview")
        self.assertEqual(case_conversation_title("67", "metadata", "Timeline?"), "Case 67 · Timeline")
        self.assertEqual(case_conversation_title("67", "documents", "Tell me about the IP report"), "Case 67 · IP report")

    def test_overview_retrieval_broadens_the_query_without_changing_filters(self):
        from acc_statements import index

        client = MagicMock()
        client.query_points.return_value.points = []
        with patch.object(cims_documents, "_published_versions", return_value=["published"]), patch.object(
            index, "get_client", return_value=client,
        ), patch.object(index, "embed", return_value=[[1.0], [2.0], [3.0]]) as embed:
            cims_documents.search_case_documents({}, "67", "What is case 67 about?")
        self.assertEqual(len(embed.call_args.args[0]), 3)
        self.assertEqual(client.query_points.call_count, 3)
        filters = [call.kwargs["query_filter"] for call in client.query_points.call_args_list]
        self.assertTrue(all(query_filter == filters[0] for query_filter in filters))
        self.assertEqual(filters[0].must[0].match.value, "67")
