import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.evidence_grounding import answer_document_question, NO_INFORMATION, UNVERIFIED_ANSWER
from acc_statements.overview import overview_hits


class DocumentAnswerTests(unittest.TestCase):
    def test_preserves_natural_overview_and_attaches_source_references(self):
        text = "I operate a sawmill in Demo Valley."
        answer = "According to Pema's statement, the case concerns a sawmill in Demo Valley. [demo-s1]"
        model = MagicMock(return_value=answer)
        result = answer_document_question("Tell me about the Demo Valley case", {"demo-s1": text}, model, "demo: Pema")
        self.assertEqual(result["answer"], answer)
        self.assertIn("demo: Pema", model.call_args.args[0])
        self.assertNotIn("response_format", model.call_args.kwargs)

    def test_invalid_source_links_do_not_replace_the_answer(self):
        model = MagicMock(return_value="A readable answer. [other-s1]")
        result = answer_document_question("Question", {"demo-s1": "Owns a mill."}, model)
        self.assertEqual(result["answer"], "A readable answer.")
        self.assertEqual(result["sentence_ids"], ["demo-s1"])

    def test_absent_fact_can_still_abstain(self):
        model = MagicMock(return_value=NO_INFORMATION)
        result = answer_document_question("What is her salary?", {"demo-s1": "Owns a mill."}, model)
        self.assertEqual(result["answer"], NO_INFORMATION)

    def test_empty_evidence_does_not_call_model(self):
        model = MagicMock()
        self.assertIn("No matching document passages", answer_document_question("Question", {}, model)["answer"])
        model.assert_not_called()

    def test_overview_selects_case_documents_with_balanced_context(self):
        docs = [{"doc_id": f"demo_{i}", "header": {"case_no": case, "name": name},
            "sentences": [{"id": f"demo_{i}-s{n}", "text": f"{place} testimony sentence {n}."} for n in range(1, 31)]}
            for i, case, name, place in ((1, "A", "Pema", "Demo Valley"), (2, "A", "Dawa", "Other place"), (3, "B", "Sonam", "Elsewhere"))]
        with patch("acc_statements.overview.load_docs", return_value=docs):
            hits = overview_hits("Tell me about the Demo Valley case", [{"doc_id": "demo_1", "sentence_ids": ["demo_1-s15"]}], max_chars=1600)
        self.assertEqual({hit["doc_id"] for hit in hits}, {"demo_1", "demo_2"})
        self.assertLessEqual(sum(len(hit["text_numbered"]) for hit in hits), 1600)
        self.assertIn("demo_2-s1", hits[1]["sentence_ids"])
        self.assertIn("demo_2-s30", hits[1]["sentence_ids"])

    def test_overview_never_expands_beyond_explicit_case_scope(self):
        docs = [{"doc_id": "demo", "header": {"case_no": "PRIVATE", "name": "Pema"},
            "sentences": [{"id": "demo-s1", "text": "Demo Valley"}]}]
        original = [{"doc_id": "allowed", "sentence_ids": []}]
        with patch("acc_statements.overview.load_docs", return_value=docs):
            self.assertEqual(overview_hits("Tell me about Pema", original, case_nos=[]), original)

    def test_non_overview_questions_keep_semantic_retrieval(self):
        with patch("acc_statements.overview.load_docs") as load:
            hits = [{"doc_id": "demo"}]
            self.assertEqual(overview_hits("What amount was paid?", hits), hits)
            load.assert_not_called()

    def test_contradiction_helpers_do_not_require_dateparser_at_import(self):
        import importlib
        import acc_statements.analyze as analyze
        with patch.dict(sys.modules, {"dateparser": None}):
            importlib.reload(analyze)
            self.assertEqual(analyze.locate_quote({"sentences": [{"id": "demo-s1", "text": "Paid 100."}]}, "Paid 100."), "demo-s1")
