import importlib
import json
import sys
import subprocess
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acc_statements import llm


class StatementGenerationTests(unittest.TestCase):
    def test_contradictions_reuses_package_index_even_when_legacy_index_exists(self):
        script = """
import sys, types
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
before = list(sys.path)
import acc_statements
assert sys.path == before, 'Package import must not expose a second index module'
canonical = types.ModuleType('acc_statements.index')
canonical.embed = lambda texts: 'shared model'
legacy = types.ModuleType('index')
legacy.embed = lambda texts: 'duplicate model'
sys.modules['acc_statements.index'] = canonical
sys.modules['index'] = legacy
sys.modules['numpy'] = types.ModuleType('numpy')
from acc_statements import contradictions
assert contradictions.embed is canonical.embed
"""
        result = subprocess.run([sys.executable, "-c", script, str(Path(__file__).resolve().parents[1])],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        fake_index = types.ModuleType("acc_statements.index")
        fake_index.embed = MagicMock()
        with patch.dict(sys.modules, {"acc_statements.index": fake_index, "numpy": types.ModuleType("numpy")}):
            importlib.import_module("acc_statements.contradictions")

    def stream(self, chunks):
        result = MagicMock(status_code=200)
        result.iter_lines.return_value = [json.dumps(chunk).encode() for chunk in chunks]
        return result

    def test_structured_generation_uses_bounded_analysis_budget(self):
        response = self.stream([{"message": {"content": "{}"}, "done": True, "done_reason": "stop"}])
        with patch.object(llm.requests, "post", return_value=response) as post:
            self.assertEqual(llm._chat([], fmt={"type": "object"}), "{}")
        self.assertEqual(post.call_args.kwargs["json"]["options"]["num_predict"], 2048)
        response.close.assert_called_once()

    def test_truncation_is_reported_before_parsing_json(self):
        response = self.stream([{"message": {"content": '{"claims": ['}, "done": True, "done_reason": "length"}])
        with patch.object(llm.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "truncated"):
                llm._chat([])

    def test_incomplete_stream_is_not_accepted(self):
        response = self.stream([{"message": {"content": "partial"}}])
        with patch.object(llm.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "before completing"):
                llm._chat([])

    def test_source_claims_need_no_model_generation(self):
        fake_index = types.ModuleType("acc_statements.index")
        fake_index.embed = MagicMock()
        with patch.dict(sys.modules, {"acc_statements.index": fake_index, "numpy": types.ModuleType("numpy")}):
            detector = importlib.import_module("acc_statements.contradictions")
        rows = [{"id": f"demo-s{i}", "text": f"Payment record number {i}."} for i in range(1, 15)]
        doc = {"doc_id": "demo", "header": {"name": "Demo Witness"}, "sentences": rows}
        with patch.object(detector, "ask_json", return_value=types.SimpleNamespace(claims=[])) as generate:
            claims = detector.extract_claims(doc)
        generate.assert_not_called()
        self.assertEqual([claim["quote"] for claim in claims], [row["text"] for row in rows])
        self.assertTrue(all(claim["verified"] for claim in claims))

    def test_truncated_pair_is_reported_as_incomplete_without_aborting_analysis(self):
        fake_index = types.ModuleType("acc_statements.index")
        fake_index.embed = MagicMock()
        with patch.dict(sys.modules, {"acc_statements.index": fake_index, "numpy": types.ModuleType("numpy")}):
            detector = importlib.import_module("acc_statements.contradictions")
        docs = [{"doc_id": name, "header": {"name": name, "case_no": "demo"},
            "sentences": [{"id": f"{name}-s1", "text": text}]} for name, text in (("a", "Paid 100."), ("b", "Paid 200."))]
        with patch.object(detector, "find_candidate_pairs", return_value=[(0, 1, 0.9)]), \
             patch.object(detector, "judge_pair", side_effect=RuntimeError("truncated")):
            result = detector.detect_contradictions(docs)
        self.assertEqual(result["pairs_judged"], 0)
        self.assertEqual(result["pairs_selected"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["contradictions"], [])

    def test_pair_judge_has_a_small_budget_and_no_repeated_model_attempts(self):
        detector = importlib.import_module("acc_statements.contradictions")
        claim = {"person": "Demo", "statement_date": "today", "claim": "Paid 100.", "quote": "Paid 100."}
        with patch.object(detector, "ask_json") as generate:
            detector.judge_pair(claim, claim)
        self.assertEqual(generate.call_args.kwargs, {"max_tokens": 512, "retries": 0})
