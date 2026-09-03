from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from plan_analysis import build_plan  # noqa: E402
from profile_chatlab_corpus import profile_chatlab  # noqa: E402
from validate_chatlab_run import validate_chatlab_run  # noqa: E402
from _common import file_sha256  # noqa: E402


class ChatLabProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = ROOT / "fixtures" / "chatlab"
        self.inventory = {
            "files": [
                {
                    "path": str(path.resolve()),
                    "source_container_id": f"SRC-{path.stem.upper()}",
                    "canonical": True,
                }
                for path in self.fixture_root.glob("*.json")
            ]
        }

    def test_real_shape_fixture_deduplicates_exports_and_ignores_runtime_json(self) -> None:
        result = profile_chatlab([self.fixture_root], inventory=self.inventory, max_samples_per_conversation=6)
        self.assertEqual(result["summary"]["recognized_chatlab_exports"], 3)
        self.assertEqual(result["summary"]["ignored_non_chatlab_json"], 1)
        self.assertEqual(result["summary"]["canonical_conversations"], 2)
        self.assertEqual(result["summary"]["variant_exports"], 1)
        self.assertEqual(result["summary"]["messages_in_canonical_exports"], 15)
        self.assertTrue(result["variant_exports"][0]["path"].endswith("group-partial.json"))
        canonical_paths = {Path(item["source_path"]).name for item in result["conversations"]}
        self.assertEqual(canonical_paths, {"group-full.json", "private.json"})

    def test_review_samples_are_bounded_stratified_and_exclude_nonsemantic_types(self) -> None:
        result = profile_chatlab([self.fixture_root], max_samples_per_conversation=6, max_content_chars=120)
        by_conversation: dict[str, list[dict]] = {}
        for sample in result["review_samples"]:
            by_conversation.setdefault(sample["conversation_id"], []).append(sample)
            self.assertIn(sample["message_type"], {0, 7, 25})
            self.assertLessEqual(len(sample["content"]), 120)
            self.assertEqual(sample["review_status"], "unreviewed_candidate")
        self.assertEqual(len(by_conversation), 2)
        self.assertTrue(all(len(rows) <= 6 for rows in by_conversation.values()))
        group = next(item for item in result["conversations"] if item["conversation_type"] == "group")
        strata = {item["time_stratum"] for item in by_conversation[group["conversation_id"]]}
        self.assertEqual(strata, {"early", "middle", "late"})

    def test_channel_aggregates_keep_denominators_and_cues_separate(self) -> None:
        result = profile_chatlab([self.fixture_root], max_samples_per_conversation=3)
        aggregates = {item["conversation_type"]: item for item in result["conversation_type_aggregates"]}
        self.assertEqual(aggregates["group"]["message_count"], 9)
        self.assertEqual(aggregates["private"]["message_count"], 6)
        self.assertEqual(aggregates["group"]["message_type_counts"]["system_notice"], 1)
        self.assertGreater(aggregates["group"]["derived_rates"]["quoted_or_reply_share_of_messages"], 0)
        self.assertIn("question_candidate", aggregates["group"]["lexical_cue_counts"])


class ScopeAwareRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.goal = "继续测试这个目录，并让宿主智能体与 Skill 配合。"
        self.inventory = {
            "summary": {
                "canonical_items": 3,
                "by_evidence_role": {"content_text": 1, "visual_layout": 1, "tabular_data": 1},
                "by_container_type": {"text_document": 1, "image": 1, "table": 1},
                "by_extension": {".json": 1, ".png": 1, ".csv": 1},
                "table_files": 1,
            },
            "files": [
                {"source_container_id": "SRC-CHAT", "path": "synthetic-chat.json", "canonical": True, "evidence_role": "content_text", "container_type": "text_document", "extension": ".json"},
                {"source_container_id": "SRC-IMAGE", "path": "synthetic.png", "canonical": True, "evidence_role": "visual_layout", "container_type": "image", "extension": ".png"},
                {"source_container_id": "SRC-TABLE", "path": "synthetic.csv", "canonical": True, "evidence_role": "tabular_data", "container_type": "table", "extension": ".csv"},
            ],
        }

    def test_open_mixed_continuation_stops_at_scope_gate(self) -> None:
        plan = build_plan(self.goal, self.inventory)
        self.assertEqual(plan["primary_route"], "inventory_and_profile")
        self.assertTrue(plan["corpus_shape"]["scope_gate_required"])
        self.assertFalse(plan["corpus_scope_gate"]["deep_analysis_allowed"])
        self.assertTrue(plan["host_context_review"]["required"])

    def test_verified_family_selection_controls_route_and_analysis_unit(self) -> None:
        gate = {
            "contract_version": "data-lens-corpus-scope-gate/1.0",
            "decision_question": self.goal,
            "next_action": "analysis_ready",
            "deep_analysis_allowed": True,
            "selected_family_id": "F-CHAT",
            "selected_source_ids": ["SRC-CHAT"],
            "selection": {"scope_type": "family", "scope_id": "F-CHAT", "valid": True},
            "families": [
                {
                    "family_id": "F-CHAT",
                    "analysis_ready": True,
                    "analysis_unit": "message_within_conversation",
                    "recommended_route": "qualitative_corpus",
                }
            ],
        }
        plan = build_plan(self.goal, self.inventory, gate)
        self.assertEqual(plan["primary_route"], "qualitative_corpus")
        self.assertEqual(plan["comparison_unit"], "message_within_conversation")
        self.assertEqual(plan["user_goal"], self.goal)
        self.assertEqual(plan["decision_question"], self.goal)
        self.assertEqual(plan["corpus_shape"]["canonical_items"], 1)

    def test_verified_whole_corpus_selection_uses_mixed_route(self) -> None:
        gate = {
            "contract_version": "data-lens-corpus-scope-gate/1.0",
            "decision_question": self.goal,
            "next_action": "analysis_ready",
            "deep_analysis_allowed": True,
            "selected_source_ids": ["SRC-CHAT", "SRC-IMAGE", "SRC-TABLE"],
            "selection": {"scope_type": "whole_corpus", "scope_id": "whole_corpus", "valid": True},
            "families": [],
        }
        plan = build_plan(self.goal, self.inventory, gate)
        self.assertEqual(plan["primary_route"], "mixed_corpus")
        self.assertEqual(plan["comparison_unit"], "family_specific")


class ChatLabRunGateTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @patch("validate_chatlab_run.validate_scope_gate", return_value=[])
    @patch("validate_chatlab_run.validate_angle_ledger", return_value=[])
    @patch("validate_chatlab_run.validate_finding_ledger", return_value=[])
    def test_final_gate_binds_source_hash_and_cross_artifact_question(
        self, _finding_validator, _angle_validator, _scope_validator
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "group.json"
            source.write_text('{"messages": []}', encoding="utf-8")
            question = "宿主和 Skill 应如何配合？"
            source_id = "SRC-GROUP"
            profile = root / "profile.json"
            scope = root / "scope.json"
            angle = root / "angle.json"
            finding = root / "finding.json"
            plan = root / "plan.json"
            self._write_json(profile, {
                "contract_version": "data-lens-chatlab-corpus-profile/0.1",
                "summary": {"canonical_conversations": 1, "messages_in_canonical_exports": 0, "review_sample_count": 0},
                "conversations": [{"source_container_id": source_id, "source_path": str(source), "source_sha256": file_sha256(source), "semantic_candidate_count": 0}],
                "failure_ledger": [],
            })
            self._write_json(scope, {"decision_question": question, "next_action": "analysis_ready", "deep_analysis_allowed": True, "selected_source_ids": [source_id]})
            self._write_json(angle, {"summary": {"decision_question": question, "adopted_count": 1}})
            self._write_json(finding, {"decision_question": question, "summary": {"core_question_answered": True, "anchor_finding_count": 1, "adopted_count": 1}})
            self._write_json(plan, {"decision_question": question, "primary_route": "qualitative_corpus"})

            valid = validate_chatlab_run(profile, scope, angle, finding, plan, "final", "deep")
            self.assertTrue(valid["valid"])
            self.assertTrue(valid["report_eligible"])

            source.write_text('{"messages": [{"content": "tampered"}]}', encoding="utf-8")
            invalid = validate_chatlab_run(profile, scope, angle, finding, plan, "final", "deep")
            self.assertFalse(invalid["valid"])
            self.assertIn("conversation_source_hash_failures:1", invalid["errors"])


if __name__ == "__main__":
    unittest.main()
