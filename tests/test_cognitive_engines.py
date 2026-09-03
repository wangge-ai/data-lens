from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validate_method_manifests import validate_repository  # noqa: E402


class CognitiveEngineAssetTests(unittest.TestCase):
    def test_router_and_contradiction_methods_are_registered_and_resolvable(self) -> None:
        registry = json.loads((ROOT / "methods" / "registry.json").read_text(encoding="utf-8"))
        registered = {item["method_id"]: item for item in registry["methods"]}
        self.assertIn("data_lens.cognitive_engine_router", registered)
        self.assertIn("data_lens.contradiction_analysis", registered)
        validation = validate_repository(ROOT)
        self.assertTrue(validation["valid"], validation["errors"])

    def test_behavioral_fixture_covers_selection_refusal_and_defer(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "contradiction-analysis" / "cases.json").read_text(encoding="utf-8")
        )
        cases = fixture["cases"]
        case_ids = [case["case_id"] for case in cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertTrue(any(case["expected_result"] == "select" for case in cases))
        self.assertTrue(any(case["expected_result"] == "not_applicable" for case in cases))
        self.assertTrue(any(case["expected_result"] == "defer" for case in cases))
        self.assertTrue(any(case["scope_ready"] is False for case in cases))
        self.assertTrue(any(case["case_type"] == "no_contradiction_control" for case in cases))

    def test_reader_language_does_not_require_theory_quotation(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "contradiction-analysis" / "cases.json").read_text(encoding="utf-8")
        )
        reader_language = fixture["reader_language"]
        self.assertEqual(reader_language["default"], "plain_modern_chinese")
        self.assertFalse(reader_language["source_quotation_required"])
        self.assertFalse(reader_language["theory_terms_required"])

    def test_selected_cases_require_a_distinct_structure_and_separate_action(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "contradiction-analysis" / "cases.json").read_text(encoding="utf-8")
        )
        selected = [case for case in fixture["cases"] if case["expected_result"] == "select"]
        required = {
            "ordinary_explanation",
            "counter_structure",
            "discriminating_prediction",
            "coupling_carrier",
            "structural_key",
            "action_priority",
        }
        for case in selected:
            with self.subTest(case_id=case["case_id"]):
                self.assertTrue(required.issubset(case))
                self.assertNotEqual(case["ordinary_explanation"], case["counter_structure"])
                self.assertNotEqual(case["structural_key"], case["action_priority"])


if __name__ == "__main__":
    unittest.main()
