from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_agent_compatibility import validate as validate_compatibility  # noqa: E402
from check_public_tree import scan as scan_public_tree  # noqa: E402
from detect_capabilities import detect  # noqa: E402
from local_vector_index import build_index, query_index  # noqa: E402
from multimodal_inventory import collect  # noqa: E402
from plan_analysis import build_plan  # noqa: E402
from r_method_runner import probe, validate_result  # noqa: E402
from select_samples import build_sample  # noqa: E402
from tabular_analysis import anomaly_candidates, change_candidate, grouped, profile, read_table  # noqa: E402
from validate_adoption_ledger import validate as validate_adoption  # noqa: E402


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class CapabilityTests(unittest.TestCase):
    def test_optional_capabilities_never_auto_install(self) -> None:
        payload = detect()
        self.assertTrue(payload["core"]["python_standard_library"]["available"])
        self.assertFalse(payload["policy"]["auto_install"])
        self.assertFalse(payload["policy"]["remote_services_enabled_by_default"])

    def test_r_probe_is_optional(self) -> None:
        payload = probe()
        self.assertEqual(payload["contract_version"], "data-lens-r-capability/1.0")
        self.assertFalse(payload["auto_install"])
        self.assertIsInstance(payload["available"], bool)

    def test_r_result_contract_validation(self) -> None:
        valid = {
            "contract_version": "data-lens-method-result/1.0",
            "method_id": "data_lens.r_descriptive_summary",
            "method_version": "0.1.0",
            "status": "succeeded",
            "results": [],
            "diagnostics": [],
        }
        self.assertEqual(validate_result(valid), [])
        self.assertTrue(validate_result({"status": "succeeded"}))


class VectorIndexTests(unittest.TestCase):
    def test_local_vector_index_is_rebuildable_candidate_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "apple.md").write_text("苹果 商品 销售 增长，来自合成样本。", encoding="utf-8")
            (source / "video.md").write_text("视频 脚本 结构，来自另一份合成样本。", encoding="utf-8")
            database = root / "index.sqlite"
            metadata = build_index(source, database, dimensions=128, chunk_chars=80, overlap=10)
            self.assertFalse(metadata["source_of_truth"])
            result = query_index(database, "苹果 销售", limit=3)
            self.assertFalse(result["source_of_truth"])
            self.assertEqual(result["results"][0]["source_path"], "apple.md")
            self.assertEqual(result["results"][0]["status"], "retrieval_candidate_only")
            self.assertIn("char_start", result["results"][0]["locator"])
            with self.assertRaises(FileExistsError):
                build_index(source, database)


class MultimodalTests(unittest.TestCase):
    def test_image_inventory_does_not_claim_semantic_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.png").write_bytes(ONE_PIXEL_PNG)
            payload = collect(root)
            self.assertEqual(payload["source_container_count"], 1)
            item = payload["items"][0]
            self.assertEqual(item["medium"], "image")
            self.assertEqual(item["semantic_review"], "required")
            self.assertEqual((item["width"], item["height"]), (1, 1))


class AdoptionTests(unittest.TestCase):
    def test_request_success_and_adoption_success_are_separate(self) -> None:
        payload = {
            "contract_version": "data-lens-adoption-ledger/1.0",
            "request": {"attempted": True, "succeeded": True, "request_count": 1},
            "evidence_index": {},
            "candidates": [
                {
                    "candidate_id": "C1",
                    "contract_valid": True,
                    "evidence_valid": False,
                    "evidence_refs": [],
                    "adopted": False,
                    "rejection_reason": "no verified evidence",
                }
            ],
            "summary": {"candidate_count": 1, "adopted_count": 0, "core_question_answered": False},
            "completion_status": "core_question_unanswered",
        }
        self.assertEqual(validate_adoption(payload), [])

    def test_complete_requires_verified_adopted_finding(self) -> None:
        payload = {
            "contract_version": "data-lens-adoption-ledger/1.0",
            "request": {"attempted": True, "succeeded": True, "request_count": 1},
            "evidence_index": {"E1": {"verified": True}},
            "candidates": [
                {
                    "candidate_id": "C1",
                    "contract_valid": True,
                    "evidence_valid": True,
                    "evidence_refs": ["E1"],
                    "adopted": True,
                }
            ],
            "summary": {"candidate_count": 1, "adopted_count": 1, "core_question_answered": True},
            "completion_status": "complete",
        }
        self.assertEqual(validate_adoption(payload), [])
        payload["evidence_index"]["E1"]["verified"] = False
        self.assertTrue(validate_adoption(payload))


class SamplingTests(unittest.TestCase):
    def test_fully_human_confirmed_units_are_not_selected_again(self) -> None:
        inventory = {
            "supplied_paths": [],
            "files": [
                {
                    "source_container_id": "done",
                    "path": "done.md",
                    "title": "已确认文章",
                    "canonical": True,
                    "evidence_role": "content_text",
                    "container_type": "article_candidate",
                    "source_family_key": "done",
                    "human_review_complete": True,
                },
                {
                    "source_container_id": "new",
                    "path": "new.md",
                    "title": "待分析文章",
                    "canonical": True,
                    "evidence_role": "content_text",
                    "container_type": "article_candidate",
                    "source_family_key": "new",
                },
            ],
        }
        sample = build_sample(inventory, "balanced_topic", 5)
        self.assertEqual([item["source_container_id"] for item in sample["selected"]], ["new"])
        self.assertEqual(sample["exclusions"]["already_human_confirmed"], 1)


class TabularMethodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "tests" / "fixtures" / "table_methods.csv"
        self.headers, self.rows = read_table(self.path)

    def test_profile_keeps_missing_and_zero_separate(self) -> None:
        result = profile(self.headers, self.rows)
        optional = next(item for item in result["columns"] if item["column"] == "optional")
        self.assertEqual(optional["missing_count"], 1)
        self.assertEqual(optional["zero_count"], 1)

    def test_grouped_descriptive_is_deterministic(self) -> None:
        result = grouped(self.rows, ["group"], ["metric"])
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["groups"][0]["metrics"]["metric"]["sum"], 40.0)
        self.assertIn("do not establish causality", result["boundaries"][0])

    def test_anomaly_and_change_are_candidates_not_causes(self) -> None:
        anomaly = anomaly_candidates(self.rows, "anomaly_metric", 3.5)
        self.assertEqual(anomaly["candidates"][0]["row_number"], 9)
        self.assertEqual(anomaly["candidates"][0]["status"], "candidate_not_error")
        change = change_candidate(self.rows, "date", "metric", 3)
        self.assertEqual(change["candidate"]["split_after"], "2026-01-04")
        self.assertIn("does not prove", change["boundaries"][0])


class RepositoryTests(unittest.TestCase):
    def test_all_method_manifests_have_registered_versions(self) -> None:
        registry = json.loads((ROOT / "methods" / "registry.json").read_text(encoding="utf-8"))
        required = {
            "contract_version", "method_id", "version", "status", "name", "question_types",
            "accepted_units", "input_shapes", "eligibility_checks", "human_gates", "implementation",
            "outputs", "evidence_requirements", "allowed_claims", "forbidden_claims", "validation",
        }
        for item in registry["methods"]:
            manifest = json.loads((ROOT / "methods" / item["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(required - manifest.keys(), set())
            self.assertEqual(manifest["method_id"], item["method_id"])
            self.assertEqual(manifest["version"], item["version"])

    def test_public_tree_and_agent_compatibility(self) -> None:
        self.assertEqual(scan_public_tree(), [])
        self.assertEqual(validate_compatibility(), [])

    def test_unified_cli_lists_commands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "data_lens.py"), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("validate-adoption", completed.stdout)
        self.assertIn("multimodal-inventory", completed.stdout)


class RoutingTests(unittest.TestCase):
    def test_generic_table_is_not_forced_into_operational_route(self) -> None:
        inventory = {
            "files": [{"canonical": True, "evidence_role": "tabular_data", "container_type": "table"}],
            "summary": {"canonical_items": 1, "table_files": 1},
        }
        plan = build_plan("分析这个 CSV 的描述统计、字段分布和异常候选", inventory)
        self.assertEqual(plan["primary_route"], "tabular_analysis")
        self.assertIn("table_profile", plan["supporting_modules"])

    def test_inventory_and_multimodal_routes_are_first_class(self) -> None:
        inventory = {
            "files": [{"canonical": True, "evidence_role": "content_text", "container_type": "document"}],
            "summary": {"canonical_items": 1},
        }
        self.assertEqual(build_plan("先盘点这里有哪些资料", inventory)["primary_route"], "inventory_and_profile")
        visual_inventory = {
            "files": [{"canonical": True, "evidence_role": "visual_layout", "container_type": "image"}],
            "summary": {"canonical_items": 1},
        }
        self.assertEqual(build_plan("分析这些图片的视觉与排版", visual_inventory)["primary_route"], "multimodal_evidence")

    def test_general_text_patterns_do_not_become_method_corpus(self) -> None:
        inventory = {
            "files": [
                {"canonical": True, "evidence_role": "content_text", "container_type": "article_candidate"},
                {"canonical": True, "evidence_role": "content_text", "container_type": "article_candidate"},
            ],
            "summary": {"canonical_items": 2},
        }
        plan = build_plan("分析这些文章的选题、结构和写作规律", inventory)
        self.assertEqual(plan["primary_route"], "qualitative_corpus")
        self.assertNotEqual(plan["primary_route"], "method_corpus")


if __name__ == "__main__":
    unittest.main()
