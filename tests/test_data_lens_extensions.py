from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_agent_compatibility import validate as validate_compatibility  # noqa: E402
from check_public_tree import scan as scan_public_tree  # noqa: E402
from build_synthesis_context import build_context  # noqa: E402
from build_finding_synthesis_context import build_context as build_deep_context  # noqa: E402
from _common import SKILL_VERSION, file_sha256, write_csv, write_json  # noqa: E402
from compile_angle_discovery import compile_angles  # noqa: E402
from compile_corpus_scope import compile_scope  # noqa: E402
from compile_deep_findings import compile_findings  # noqa: E402
from detect_capabilities import detect  # noqa: E402
from local_vector_index import build_index, query_index  # noqa: E402
from multimodal_inventory import collect  # noqa: E402
from ocr_evidence import parse_tsv, run_ocr  # noqa: E402
from pdf_evidence import build_pdf_evidence, page_indices, parse_page_spec, parse_pdfinfo  # noqa: E402
from profile_workbook_integrity import profile_workbooks  # noqa: E402
from plan_analysis import build_plan  # noqa: E402
from r_method_runner import probe, run_method, validate_result  # noqa: E402
from select_samples import build_sample  # noqa: E402
from tabular_analysis import anomaly_candidates, change_candidate, grouped, profile, read_table  # noqa: E402
from transcribe_media import build_transcription_evidence, clip_bounds  # noqa: E402
from validate_adoption_ledger import validate as validate_adoption  # noqa: E402
from validate_finding_ledger import validate as validate_finding_ledger  # noqa: E402
from validate_corpus_scope_gate import validate as validate_scope_gate  # noqa: E402
from validate_method_manifests import validate_repository as validate_method_manifests  # noqa: E402
from video_evidence import build_video_evidence, evenly_spaced_timestamps, parse_duration_ms, parse_timestamp_spec  # noqa: E402
from workbook_media import bounded_media_sample, inventory_workbook_media  # noqa: E402


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AngleDiscoveryExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = ROOT / "fixtures" / "angle-discovery"
        self.candidates = json.loads((self.fixture_root / "candidates-valid.json").read_text(encoding="utf-8"))
        self.evidence = json.loads((self.fixture_root / "evidence-cards.json").read_text(encoding="utf-8"))

    def test_candidate_adapter_contract_evidence_and_adoption_are_separate(self) -> None:
        ledger = compile_angles(self.candidates, self.evidence)
        self.assertEqual(validate_adoption(ledger), [])
        self.assertTrue(ledger["request"]["succeeded"])
        self.assertEqual(ledger["summary"]["candidate_count"], 2)
        self.assertEqual(ledger["summary"]["adopted_count"], 1)
        self.assertTrue(ledger["candidates"][0]["contract_valid"])
        self.assertTrue(ledger["candidates"][0]["evidence_valid"])
        self.assertTrue(ledger["candidates"][0]["adopted"])
        self.assertFalse(ledger["candidates"][1]["adopted"])
        self.assertEqual(ledger["completion_status"], "preliminary")
        self.assertFalse(ledger["summary"]["core_question_answered"])

    def test_candidate_adapter_normalizes_bounded_model_aliases_before_validation(self) -> None:
        canonical = copy.deepcopy(self.candidates)
        first = canonical["candidates"][0]
        first["id"] = first.pop("candidate_id")
        first["status"] = first.pop("proposed_status")
        first["reason"] = first.pop("why_worthwhile")
        first["possible_counterexample"] = first.pop("counterexample_check")
        payload = {
            "decision_question": canonical["decision_question"],
            "request": canonical["request"],
            "angles": [first],
        }
        ledger = compile_angles(payload, self.evidence)
        self.assertEqual(ledger["candidates"][0]["candidate_id"], "A-QUALITY")
        self.assertTrue(ledger["candidates"][0]["contract_valid"])
        self.assertTrue(ledger["candidates"][0]["adopted"])

    def test_successful_candidate_response_does_not_adopt_unverified_evidence(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        candidates["candidates"][0]["evidence_refs"] = ["E-UNREVIEWED"]
        ledger = compile_angles(candidates, self.evidence)
        candidate = ledger["candidates"][0]
        self.assertTrue(ledger["request"]["succeeded"])
        self.assertTrue(candidate["contract_valid"])
        self.assertFalse(candidate["evidence_valid"])
        self.assertFalse(candidate["adopted"])
        self.assertEqual(ledger["completion_status"], "core_question_unanswered")

    def test_failed_request_cannot_adopt_a_valid_angle(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        candidates["request"]["succeeded"] = False
        ledger = compile_angles(candidates, self.evidence)
        self.assertFalse(ledger["candidates"][0]["adopted"])
        self.assertIn("request_not_succeeded", ledger["candidates"][0]["rejection_reason"])

    def test_missing_angle_contract_field_blocks_adoption(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        candidates["candidates"][0]["analysis_unit"] = ""
        ledger = compile_angles(candidates, self.evidence)
        self.assertFalse(ledger["candidates"][0]["contract_valid"])
        self.assertFalse(ledger["candidates"][0]["adopted"])

    def test_angle_limits_fail_instead_of_order_truncation(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        template = candidates["candidates"][1]
        candidates["candidates"] = [dict(template, candidate_id=f"R-{index}") for index in range(9)]
        with self.assertRaisesRegex(ValueError, "at most 8"):
            compile_angles(candidates, self.evidence)

    def test_synthesis_context_reads_verified_cards_only_with_budget(self) -> None:
        ledger = compile_angles(self.candidates, self.evidence)
        context = build_context(ledger, max_cards=1, max_chars=2_000)
        self.assertEqual(context["contract_version"], "data-lens-synthesis-context/1.0")
        self.assertEqual(context["budget"]["used_cards"], 1)
        self.assertLessEqual(context["budget"]["used_chars"], 2_000)
        self.assertEqual({card["evidence_id"] for card in context["verified_evidence_cards"]}, {"E-SCOPE"})
        self.assertIn("card_budget", {item["reason"] for item in context["omitted"]})


class CorpusScopeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        root = ROOT / "fixtures" / "corpus-scope"
        self.inventory = json.loads((root / "catch-all-inventory.json").read_text(encoding="utf-8"))
        self.evidence = json.loads((root / "catch-all-evidence.json").read_text(encoding="utf-8"))
        self.candidates = json.loads((root / "catch-all-candidates.json").read_text(encoding="utf-8"))

    def test_catch_all_folder_stops_at_family_selection(self) -> None:
        gate = compile_scope(self.candidates, self.evidence, self.inventory)
        self.assertEqual(validate_scope_gate(gate), [])
        self.assertEqual(gate["next_action"], "selection_required")
        self.assertFalse(gate["deep_analysis_allowed"])
        self.assertFalse(gate["whole_corpus_synthesis_allowed"])
        self.assertEqual(gate["coverage"]["ready_family_count"], 3)
        self.assertIn("SRC-U1", gate["coverage"]["unassigned_source_ids"])
        plan = build_plan(self.candidates["decision_question"], self.inventory)
        self.assertEqual(plan["primary_route"], "inventory_and_profile")
        self.assertTrue(plan["corpus_shape"]["scope_gate_required"])
        self.assertFalse(plan["corpus_scope_gate"]["deep_analysis_allowed"])

    def test_selected_family_unlocks_only_that_family(self) -> None:
        selected = copy.deepcopy(self.candidates)
        selected["selection"] = {
            "scope_type": "family",
            "scope_id": "F-BUSINESS",
            "basis": "user_selected",
            "authorized_by_user": True,
        }
        gate = compile_scope(selected, self.evidence, self.inventory)
        self.assertEqual(validate_scope_gate(gate), [])
        self.assertEqual(gate["next_action"], "analysis_ready")
        self.assertTrue(gate["deep_analysis_allowed"])
        self.assertEqual(set(gate["selected_source_ids"]), {"SRC-B1", "SRC-B2"})
        plan = build_plan(selected["decision_question"], self.inventory, gate)
        self.assertEqual(plan["corpus_shape"]["canonical_items"], 2)
        self.assertEqual(plan["corpus_scope_gate"]["selected_family_id"], "F-BUSINESS")
        self.assertNotEqual(plan["primary_route"], "mixed_corpus")

    def test_catch_all_cannot_be_authorized_as_whole_corpus(self) -> None:
        selected = copy.deepcopy(self.candidates)
        selected["selection"] = {
            "scope_type": "whole_corpus",
            "scope_id": "whole_corpus",
            "basis": "explicit_shared_scope",
            "authorized_by_user": True,
        }
        gate = compile_scope(selected, self.evidence, self.inventory)
        self.assertFalse(gate["deep_analysis_allowed"])
        self.assertIn("whole-corpus synthesis requires", " ".join(gate["selection"]["errors"]))


class DeepFindingEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        root = ROOT / "fixtures" / "deep-findings"
        self.evidence = json.loads((root / "evidence-cards.json").read_text(encoding="utf-8"))
        self.candidates = json.loads((root / "candidates.json").read_text(encoding="utf-8"))
        self.inventory = {
            "files": [
                {"source_container_id": f"SRC-{letter}", "canonical": True, "path": f"sanitized/{letter}.md", "extension": ".md", "evidence_role": "content_text", "container_type": "article_candidate"}
                for letter in "ABCD"
            ],
            "summary": {"canonical_items": 4},
        }
        scope_candidates = {
            "decision_question": self.candidates["decision_question"],
            "request": {"attempted": True, "succeeded": True, "provider": "fixture", "request_count": 1},
            "shared_scope": {"shared_object_status": "confirmed", "shared_object": "同一批文章", "shared_problem_status": "confirmed", "shared_problem": "寻找可验证的结构实验变量", "question_spans_families": False, "evidence_refs": ["E-SCOPE"]},
            "families": [{
                "family_id": "F-ARTICLES", "label": "同一批文章", "shared_object": "四篇文章", "analysis_unit": "article",
                "recommended_route": "qualitative_corpus", "source_container_ids": [f"SRC-{letter}" for letter in "ABCD"],
                "candidate_questions": [self.candidates["decision_question"]], "readiness": "ready", "evidence_refs": ["E-SCOPE"],
            }],
            "selection": {"scope_type": "family", "scope_id": "F-ARTICLES", "basis": "user_selected", "authorized_by_user": True},
        }
        scope_evidence = {"cards": [{"id": "E-SCOPE", "claim": "四个来源属于同一批待分析文章。", "source": "sanitized-inventory.json", "locator": {"type": "json_pointer", "pointer": "/files"}, "verified": True, "family_id": "F-ARTICLES", "lane": "source_metadata"}]}
        self.scope_gate = compile_scope(scope_candidates, scope_evidence, self.inventory)

    def test_anchor_requires_full_deep_quality_chain(self) -> None:
        ledger = compile_findings(self.candidates, self.evidence, self.scope_gate, ROOT / "fixtures" / "deep-findings")
        self.assertEqual(validate_finding_ledger(ledger), [])
        self.assertEqual(ledger["summary"]["adopted_count"], 1)
        self.assertEqual(ledger["summary"]["anchor_finding_count"], 1)
        self.assertTrue(ledger["summary"]["core_question_answered"])
        self.assertTrue(ledger["candidates"][0]["anchor_eligible"])
        self.assertFalse(ledger["candidates"][1]["adopted"])
        self.assertIn("evidence_invalid", ledger["candidates"][1]["rejection_reason"])

    def test_counterexample_search_cannot_be_skipped(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        candidates["candidates"] = [candidates["candidates"][0]]
        candidates["candidates"][0]["counterexample_search"] = {"status": "not_completed", "description": "尚未检查", "evidence_refs": []}
        ledger = compile_findings(candidates, self.evidence, self.scope_gate, ROOT / "fixtures" / "deep-findings")
        self.assertFalse(ledger["candidates"][0]["adopted"])
        self.assertFalse(ledger["summary"]["core_question_answered"])

    def test_missing_robustness_allows_no_anchor_completion(self) -> None:
        candidates = copy.deepcopy(self.candidates)
        candidates["candidates"] = [candidates["candidates"][0]]
        candidates["candidates"][0]["robustness_checks"] = []
        ledger = compile_findings(candidates, self.evidence, self.scope_gate, ROOT / "fixtures" / "deep-findings")
        self.assertTrue(ledger["candidates"][0]["adopted"])
        self.assertFalse(ledger["candidates"][0]["anchor_eligible"])
        self.assertFalse(ledger["summary"]["core_question_answered"])
        self.assertEqual(ledger["completion_status"], "partial")

    def test_unselected_scope_blocks_finding_adoption(self) -> None:
        blocked = copy.deepcopy(self.scope_gate)
        blocked["next_action"] = "selection_required"
        blocked["deep_analysis_allowed"] = False
        ledger = compile_findings(self.candidates, self.evidence, blocked, ROOT / "fixtures" / "deep-findings")
        self.assertEqual(ledger["summary"]["adopted_count"], 0)
        self.assertTrue(all(not item["adopted"] for item in ledger["candidates"]))

    def test_deep_synthesis_preserves_evidence_roles_and_boundaries(self) -> None:
        ledger = compile_findings(self.candidates, self.evidence, self.scope_gate, ROOT / "fixtures" / "deep-findings")
        context = build_deep_context(ledger, max_findings=2, max_cards=8, max_chars=10_000)
        self.assertEqual(context["contract_version"], "data-lens-deep-synthesis-context/1.0")
        self.assertEqual(context["budget"]["used_findings"], 1)
        finding = context["adopted_findings"][0]
        self.assertEqual(finding["evidence_roles"]["counter"], ["E-C1"])
        self.assertTrue(finding["boundaries"])


class WorkbookHardeningTests(unittest.TestCase):
    def _rewrite_dimension(self, path: Path, value: str) -> None:
        rewritten = path.with_name(path.stem + "-rewritten.xlsx")
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(rewritten, "w") as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    text = payload.decode("utf-8")
                    text = text.replace('ref="A1:C2"', f'ref="{value}"')
                    payload = text.encode("utf-8")
                target.writestr(item, payload)
        rewritten.replace(path)

    def _remove_dimension(self, path: Path) -> None:
        rewritten = path.with_name(path.stem + "-unsized.xlsx")
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(rewritten, "w") as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    text = payload.decode("utf-8")
                    start = text.index("<dimension")
                    end = text.index("/>", start) + 2
                    payload = (text[:start] + text[end:]).encode("utf-8")
                target.writestr(item, payload)
        rewritten.replace(path)

    def test_workbook_integrity_separates_errors_from_review_candidates(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "alpha.xlsx"
            second = root / "beta.xlsx"
            for path in (first, second):
                workbook = Workbook()
                sheet = workbook.active
                sheet["A1"] = "Invented reusable template sentence"
                sheet["B2"] = 1.5
                sheet["B2"].number_format = "0.00%"
                sheet["C2"] = "#DIV/0!"
                sheet["C2"].data_type = "e"
                workbook.save(path)
            self._rewrite_dimension(first, "A1")
            rules = root / "rules.json"
            rules.write_text(json.dumps({"rules": [{"rule_id": "scope", "workbook_pattern": "alpha", "forbidden_terms": ["template sentence"], "reason": "synthetic scope check"}]}), encoding="utf-8")
            result = profile_workbooks([first, second], max_cells_per_sheet=100, term_rules=rules)
            self.assertEqual(result["contract_version"], "data-lens-workbook-integrity/1.0")
            self.assertEqual(result["totals"]["formula_errors"], 2)
            self.assertEqual(result["totals"]["percent_format_candidates"], 2)
            self.assertEqual(result["totals"]["configured_term_candidates"], 1)
            self.assertEqual(result["totals"]["stale_dimension_sheets"], 1)
            self.assertEqual(len(result["cross_workbook_repeat_candidates"]), 1)
            self.assertIn("not confirmed semantic errors", result["interpretation_boundary"])
            self.assertEqual(result["totals"]["formula_errors_status"], "complete")
            self.assertTrue(result["workbooks"][0]["sheets"][0]["safe_for_row_bound_inference"])

    def test_workbook_integrity_handles_unsized_sheets_and_marks_truncation_as_lower_bound(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            workbook_path = Path(temporary) / "unsized.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            for row in range(1, 21):
                for column in range(1, 6):
                    sheet.cell(row=row, column=column, value=f"R{row}C{column}")
            workbook.save(workbook_path)
            self._remove_dimension(workbook_path)
            result = profile_workbooks([workbook_path], max_cells_per_sheet=10)
            profile = result["workbooks"][0]["sheets"][0]
            self.assertEqual(profile["declared_dimension_status"], "missing_unsized")
            self.assertTrue(profile["scan_truncated"])
            self.assertEqual(profile["observed_dimension_status"], "lower_bound_due_to_scan_limit")
            self.assertFalse(profile["safe_for_row_bound_inference"])
            self.assertEqual(result["totals"]["formula_errors_status"], "lower_bound")

    def test_wps_cell_images_are_located_and_sampled_across_sheets(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workbook_path = root / "synthetic-wps.xlsx"
            workbook = Workbook()
            workbook.active.title = "First"
            workbook.active["A1"] = '=DISPIMG("ID_SYNTH_1",1)'
            second = workbook.create_sheet("Second")
            second["B2"] = '=DISPIMG("ID_SYNTH_2",1)'
            workbook.save(workbook_path)
            fixture_root = ROOT / "fixtures" / "workbooks"
            with zipfile.ZipFile(workbook_path, "a") as archive:
                archive.writestr("xl/cellimages.xml", (fixture_root / "wps-cellimages.xml").read_bytes())
                archive.writestr("xl/_rels/cellimages.xml.rels", (fixture_root / "wps-cellimages.xml.rels").read_bytes())
                archive.writestr("xl/media/synthetic1.png", ONE_PIXEL_PNG)
                archive.writestr("xl/media/synthetic2.png", ONE_PIXEL_PNG)
            output_dir = root / "sample"
            result = inventory_workbook_media([workbook_path], output_dir, True, max_images=2, max_cells_per_sheet=100)
            self.assertEqual(result["contract_version"], "data-lens-workbook-media/1.0")
            self.assertEqual(len(result["media"]), 2)
            self.assertEqual(len(result["sample"]["selected_media_ids"]), 2)
            self.assertEqual({item["mapping_status"] for item in result["media"]}, {"located"})
            self.assertEqual({item["locators"][0]["sheet"] for item in result["media"]}, {"First", "Second"})
            self.assertTrue(all(item["extraction"]["status"] == "extracted" for item in result["media"]))
            self.assertEqual(result["failure_ledger"], [])

    def test_workbook_media_sample_is_spread_not_sequential_first_n(self) -> None:
        entries = [
            {
                "media_id": f"WM-{index}",
                "workbook_sha256": "synthetic",
                "image_id": f"ID-{index}",
                "archive_member": f"xl/media/image{index}.png",
                "locators": [{"sheet": "Only", "cell": f"A{index}"}],
            }
            for index in range(1, 6)
        ]
        selected = bounded_media_sample(entries, 2)
        self.assertEqual(selected, ["WM-3", "WM-1"])
        self.assertNotEqual(selected, ["WM-1", "WM-2"])


class CapabilityTests(unittest.TestCase):
    def test_optional_capabilities_never_auto_install(self) -> None:
        payload = detect()
        self.assertTrue(payload["core"]["python_standard_library"]["available"])
        self.assertFalse(payload["policy"]["auto_install"])
        self.assertFalse(payload["policy"]["remote_services_enabled_by_default"])

    def test_capability_report_separates_installation_from_workflow_readiness(self) -> None:
        payload = detect()
        self.assertEqual(payload["contract_version"], "data-lens-capabilities/2.0")
        for group in ("core", "optional_python", "optional_executables"):
            for capability in payload[group].values():
                self.assertEqual(capability["available"], capability["installed"])
                self.assertIn(capability["state"], {"unavailable", "installed_only", "wired", "fixture_validated", "production_ready"})
        semantic = payload["optional_python"]["semantic_embeddings"]
        self.assertFalse(semantic["wired"])
        self.assertIsNone(semantic["entrypoint"])
        ocr = payload["optional_executables"]["ocr"]
        self.assertTrue(ocr["wired"])
        self.assertTrue(ocr["fixture_validated"])
        self.assertFalse(ocr["production_ready"])

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

    def test_replace_refuses_non_data_lens_file_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "sample.md").write_text("合成向量样本。", encoding="utf-8")
            ordinary = root / "important.txt"
            ordinary.write_text("must remain unchanged", encoding="utf-8")
            before = file_sha256(ordinary)
            with self.assertRaisesRegex(ValueError, "Data Lens vector index"):
                build_index(source, ordinary, replace=True)
            self.assertEqual(file_sha256(ordinary), before)
            self.assertEqual(ordinary.read_text(encoding="utf-8"), "must remain unchanged")

    def test_failed_replace_keeps_previous_index_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            sample = source / "sample.md"
            sample.write_text("初始合成样本。", encoding="utf-8")
            database = root / "index.sqlite"
            build_index(source, database, dimensions=128)
            before = file_sha256(database)
            with patch("local_vector_index.read_text_fallback", side_effect=RuntimeError("synthetic build failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic build failure"):
                    build_index(source, database, dimensions=128, replace=True)
            self.assertEqual(file_sha256(database), before)
            self.assertEqual(list(root.glob(f".{database.name}.*.tmp")), [])


class FileWriteSafetyTests(unittest.TestCase):
    def _assert_cli_collision_preserves(self, script: str, source: Path, extra: list[str] | None = None) -> None:
        before = file_sha256(source)
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / script), str(source), *(extra or []), "--output", str(source)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("must not overwrite", completed.stderr)
        self.assertEqual(file_sha256(source), before)

    def test_inventory_rejects_single_source_output_collision_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.txt"
            source.write_text("source bytes must remain unchanged", encoding="utf-8")
            before = file_sha256(source)
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "inventory_inputs.py"), str(source), "--output", str(source)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must not overwrite", completed.stderr)
            self.assertEqual(file_sha256(source), before)

    def test_inventory_rejects_existing_file_inside_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            protected = source / "existing.json"
            protected.write_text('{"source": true}', encoding="utf-8")
            before = file_sha256(protected)
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "inventory_inputs.py"), str(source), "--output", str(protected)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must not overwrite", completed.stderr)
            self.assertEqual(file_sha256(protected), before)

    def test_profile_and_multimodal_clis_reject_collisions_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("profile_pdf_corpus.py", root / "source.pdf", ["--max-ocr-pages", "3"]),
                ("profile_workbook_integrity.py", root / "source.xlsx", []),
                ("multimodal_inventory.py", root / "source.png", []),
                ("ocr_evidence.py", root / "ocr-source.png", []),
            )
            for script, source, extra in cases:
                source.write_bytes(b"synthetic source bytes")
                with self.subTest(script=script):
                    self._assert_cli_collision_preserves(script, source, extra)

    def test_r_adapter_rejects_input_output_collision_before_runtime_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.json"
            source.write_text('{"source": true}', encoding="utf-8")
            before = file_sha256(source)
            script = ROOT / "methods" / "implementations" / "r" / "descriptive_summary.R"
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                run_method(script, source, source)
            self.assertEqual(file_sha256(source), before)

    def test_atomic_json_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "ledger.json"
            destination.write_text('{"stable": true}', encoding="utf-8")
            before = file_sha256(destination)
            with patch("_common.os.replace", side_effect=OSError("synthetic replace failure")):
                with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                    write_json(destination, {"new": True})
            self.assertEqual(file_sha256(destination), before)
            self.assertEqual(list(destination.parent.glob(f".{destination.name}.*.tmp")), [])

    def test_atomic_csv_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "ledger.csv"
            destination.write_text("stable\n", encoding="utf-8")
            before = file_sha256(destination)
            with patch("_common.os.replace", side_effect=OSError("synthetic replace failure")):
                with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                    write_csv(destination, ["value"], [{"value": "new"}])
            self.assertEqual(file_sha256(destination), before)
            self.assertEqual(list(destination.parent.glob(f".{destination.name}.*.tmp")), [])


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

    def test_tesseract_tsv_fixture_keeps_text_confidence_and_locators(self) -> None:
        parsed = parse_tsv((ROOT / "fixtures" / "ocr" / "mixed_chi_eng_psm6.tsv").read_text(encoding="utf-8"))
        self.assertIn("数据", parsed["raw_text"])
        self.assertEqual(parsed["metrics"]["word_count"], 5)
        self.assertEqual(parsed["words"][0]["locator"]["bbox"], [20, 20, 80, 32])
        self.assertIsInstance(parsed["metrics"]["mean_confidence"], float)

    def test_tesseract_tsv_literal_quote_does_not_swallow_following_rows(self) -> None:
        parsed = parse_tsv((ROOT / "fixtures" / "ocr" / "quote-token.tsv").read_text(encoding="utf-8"))
        self.assertEqual([word["text"] for word in parsed["words"]], ['"', "调查", "证据"])
        self.assertEqual(parsed["metrics"]["word_count"], 3)
        self.assertNotIn("\t", parsed["raw_text"])

    def test_ocr_execution_retains_bounded_candidates_without_semantic_adoption(self) -> None:
        fixtures = {
            "6": (ROOT / "fixtures" / "ocr" / "mixed_chi_eng_psm6.tsv").read_text(encoding="utf-8"),
            "11": (ROOT / "fixtures" / "ocr" / "mixed_chi_eng_psm11.tsv").read_text(encoding="utf-8"),
        }

        def fake_runner(command, **kwargs):
            if "--version" in command:
                return subprocess.CompletedProcess(command, 0, "tesseract v5.synthetic\n", "")
            if "--list-langs" in command:
                return subprocess.CompletedProcess(command, 0, "List of available languages (2):\nchi_sim\neng\n", "")
            psm = command[command.index("--psm") + 1]
            return subprocess.CompletedProcess(command, 0, fixtures[psm], "")

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "synthetic.png"
            source.write_bytes(ONE_PIXEL_PNG)
            payload = run_ocr(source, runner=fake_runner, executable="synthetic-tesseract")
        self.assertEqual(payload["status"], "succeeded")
        result = payload["results"][0]
        self.assertEqual(result["processing_state"], "ocr_complete")
        self.assertEqual(result["semantic_review_status"], "not_reviewed")
        self.assertEqual(result["selection_status"], "algorithmic_candidate_only")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertTrue(all(candidate["adoption_status"] == "not_adopted" for candidate in result["candidates"]))
        self.assertTrue(all(candidate["raw_text"] for candidate in result["candidates"]))

    def test_ocr_rejects_missing_language_and_malformed_tsv(self) -> None:
        def fake_runner(command, **kwargs):
            if "--version" in command:
                return subprocess.CompletedProcess(command, 0, "tesseract v5.synthetic\n", "")
            return subprocess.CompletedProcess(command, 0, "List of available languages (1):\neng\n", "")

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "synthetic.png"
            source.write_bytes(ONE_PIXEL_PNG)
            with self.assertRaisesRegex(ValueError, "missing Tesseract language data"):
                run_ocr(source, runner=fake_runner, executable="synthetic-tesseract")
        with self.assertRaisesRegex(ValueError, "invalid Tesseract TSV header"):
            parse_tsv("text\tconf\nhello\t90\n")

    def test_ocr_rejects_unbounded_psm_and_unsafe_language_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "synthetic.png"
            source.write_bytes(ONE_PIXEL_PNG)
            with self.assertRaisesRegex(ValueError, "one to three supported PSM"):
                run_ocr(source, psms=(3, 4, 6, 11), executable="synthetic-tesseract")
            with self.assertRaisesRegex(ValueError, "plus-separated"):
                run_ocr(source, languages="chi_sim;unexpected", executable="synthetic-tesseract")

    def test_ocr_cli_never_overwrites_source_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "synthetic.png"
            source.write_bytes(ONE_PIXEL_PNG)
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "ocr_evidence.py"), str(source), "--output", str(source)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must not overwrite", completed.stderr)
            self.assertEqual(source.read_bytes(), ONE_PIXEL_PNG)

    def test_pdf_page_selection_is_bounded_and_not_first_n(self) -> None:
        self.assertEqual(page_indices(3, 6), [1, 2, 3])
        selected = page_indices(20, 4)
        self.assertEqual((selected[0], selected[-1]), (1, 20))
        self.assertNotEqual(selected, [1, 2, 3, 4])
        self.assertEqual(parse_page_spec("1,3-4", 20, 4), [1, 3, 4])
        with self.assertRaisesRegex(ValueError, "maximum"):
            parse_page_spec("1-5", 20, 4)
        self.assertEqual(parse_pdfinfo((ROOT / "fixtures" / "pdf" / "pdfinfo-three-pages.txt").read_text(encoding="utf-8")), 3)

    def test_pdf_pipeline_keeps_page_hashes_ocr_and_source_integrity(self) -> None:
        info_text = (ROOT / "fixtures" / "pdf" / "pdfinfo-three-pages.txt").read_text(encoding="utf-8")

        def fake_runner(command, **kwargs):
            if command[0] == "synthetic-pdfinfo":
                return subprocess.CompletedProcess(command, 0, info_text, "")
            Path(command[-1] + ".png").write_bytes(ONE_PIXEL_PNG)
            return subprocess.CompletedProcess(command, 0, "", "")

        def fake_ocr(source, **kwargs):
            return {
                "contract_version": "data-lens-method-result/1.0",
                "method_id": "data_lens.tesseract_ocr",
                "method_version": "0.1.0",
                "status": "succeeded",
                "results": [{"source_sha256": "synthetic", "semantic_review_status": "not_reviewed"}],
                "diagnostics": [],
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.pdf"
            source_bytes = b"%PDF-1.7\nsynthetic fixture shape\n%%EOF\n"
            source.write_bytes(source_bytes)
            output = root / "evidence"
            payload = build_pdf_evidence(
                source,
                output,
                page_spec="1,3",
                max_pages=2,
                runner=fake_runner,
                ocr_function=fake_ocr,
                pdftoppm="synthetic-pdftoppm",
                pdfinfo="synthetic-pdfinfo",
            )
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(payload["status"], "succeeded")
            result = payload["results"][0]
            self.assertTrue(result["source_unchanged"])
            self.assertEqual(result["selected_pages"], [1, 3])
            self.assertEqual(result["semantic_review_status"], "not_reviewed")
            self.assertEqual(result["failure_ledger"], [])
            self.assertTrue(all(page["pdf_locator"]["source_sha256"] == result["source_sha256"] for page in result["pages"]))
            self.assertTrue(all(page["rendered_sha256"] for page in result["pages"]))
            self.assertTrue(all(page["ocr_output_sha256"] for page in result["pages"]))
            self.assertTrue((output / "pdf-evidence.json").is_file())

    def test_pdf_failures_are_retained_once_without_retry(self) -> None:
        info_text = (ROOT / "fixtures" / "pdf" / "pdfinfo-three-pages.txt").read_text(encoding="utf-8")
        render_calls: dict[int, int] = {}

        def fake_runner(command, **kwargs):
            if command[0] == "synthetic-pdfinfo":
                return subprocess.CompletedProcess(command, 0, info_text, "")
            page = int(command[command.index("-f") + 1])
            render_calls[page] = render_calls.get(page, 0) + 1
            if page == 2:
                return subprocess.CompletedProcess(command, 9, "", "synthetic render failure")
            Path(command[-1] + ".png").write_bytes(ONE_PIXEL_PNG)
            return subprocess.CompletedProcess(command, 0, "", "")

        def fake_ocr(source, **kwargs):
            if source.stem.endswith("0003"):
                raise RuntimeError("synthetic OCR failure")
            return {
                "contract_version": "data-lens-method-result/1.0",
                "method_id": "data_lens.tesseract_ocr",
                "method_version": "0.1.0",
                "status": "succeeded",
                "results": [],
                "diagnostics": [],
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.pdf"
            source.write_bytes(b"%PDF synthetic")
            payload = build_pdf_evidence(
                source,
                root / "evidence",
                max_pages=3,
                runner=fake_runner,
                ocr_function=fake_ocr,
                pdftoppm="synthetic-pdftoppm",
                pdfinfo="synthetic-pdfinfo",
            )
        result = payload["results"][0]
        self.assertEqual(result["completion_status"], "partial")
        self.assertEqual(render_calls, {1: 1, 2: 1, 3: 1})
        self.assertEqual({item["stage"] for item in result["failure_ledger"]}, {"render", "ocr"})
        self.assertTrue(all(item["retry_status"] == "not_retried" for item in result["failure_ledger"]))

    def test_pdf_rejects_unbounded_or_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.pdf"
            source.write_bytes(b"%PDF synthetic")
            output = root / "evidence"
            output.mkdir()
            (output / "keep.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "must be empty"):
                build_pdf_evidence(source, output, pdftoppm="synthetic", pdfinfo="synthetic")
            with self.assertRaisesRegex(ValueError, "between 1 and 30"):
                build_pdf_evidence(source, root / "other", max_pages=31, pdftoppm="synthetic", pdfinfo="synthetic")

    def test_pdf_timeout_writes_failure_ledger_without_retry(self) -> None:
        calls = 0

        def timeout_runner(command, **kwargs):
            nonlocal calls
            calls += 1
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.pdf"
            output = root / "evidence"
            source.write_bytes(b"%PDF synthetic")
            payload = build_pdf_evidence(source, output, runner=timeout_runner, pdftoppm="synthetic", pdfinfo="synthetic")
            self.assertTrue((output / "pdf-evidence.json").is_file())
        self.assertEqual(calls, 1)
        self.assertEqual(payload["results"][0]["failure_ledger"][0]["stage"], "pdfinfo_timeout")
        self.assertEqual(payload["results"][0]["recovery"]["next_attempt_requires"], "new_empty_output_directory")

    def test_video_timestamps_are_bounded_and_distributed(self) -> None:
        fixture = (ROOT / "fixtures" / "video" / "ffprobe-ten-seconds.json").read_text(encoding="utf-8")
        self.assertEqual(parse_duration_ms(fixture), 10_000)
        selected = evenly_spaced_timestamps(10_000, 4)
        self.assertEqual(selected, [2000, 4000, 6000, 8000])
        self.assertNotEqual(selected, [0, 1, 2, 3])
        self.assertEqual(parse_timestamp_spec("0.5,8.25", 10_000, 3), [500, 8250])
        with self.assertRaisesRegex(ValueError, "maximum"):
            parse_timestamp_spec("1,2,3,4", 10_000, 3)

    def test_video_frame_pipeline_keeps_timestamp_hashes_and_failures(self) -> None:
        probe_text = (ROOT / "fixtures" / "video" / "ffprobe-ten-seconds.json").read_text(encoding="utf-8")
        extraction_calls: dict[int, int] = {}

        def fake_runner(command, **kwargs):
            if command[0] == "synthetic-ffprobe":
                return subprocess.CompletedProcess(command, 0, probe_text, "")
            timestamp_ms = round(float(command[command.index("-ss") + 1]) * 1000)
            extraction_calls[timestamp_ms] = extraction_calls.get(timestamp_ms, 0) + 1
            if timestamp_ms == 5000:
                return subprocess.CompletedProcess(command, 8, "", "synthetic frame failure")
            Path(command[-1]).write_bytes(ONE_PIXEL_PNG)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            source_bytes = b"synthetic video fixture shape"
            source.write_bytes(source_bytes)
            payload = build_video_evidence(
                source,
                root / "evidence",
                timestamp_spec="1,5,9",
                max_frames=3,
                runner=fake_runner,
                ffmpeg="synthetic-ffmpeg",
                ffprobe="synthetic-ffprobe",
            )
            self.assertEqual(source.read_bytes(), source_bytes)
        result = payload["results"][0]
        self.assertEqual(result["completion_status"], "partial")
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(extraction_calls, {1000: 1, 5000: 1, 9000: 1})
        self.assertEqual(result["frames"][0]["source_locator"]["timestamp_ms"], 1000)
        self.assertTrue(result["frames"][0]["frame_sha256"])
        self.assertEqual(result["failure_ledger"][0]["retry_status"], "not_retried")
        self.assertEqual(result["semantic_review_status"], "not_reviewed")

    def test_video_timeout_writes_failure_ledger_without_retry(self) -> None:
        calls = 0

        def timeout_runner(command, **kwargs):
            nonlocal calls
            calls += 1
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            output = root / "evidence"
            source.write_bytes(b"synthetic video")
            payload = build_video_evidence(source, output, runner=timeout_runner, ffmpeg="synthetic", ffprobe="synthetic")
            self.assertTrue((output / "video-evidence.json").is_file())
        self.assertEqual(calls, 1)
        self.assertEqual(payload["results"][0]["failure_ledger"][0]["stage"], "duration_probe_timeout")
        self.assertFalse(payload["results"][0]["recovery"]["automatic_retry"])

    def test_transcription_requires_bounded_clip_and_local_checkpoint(self) -> None:
        self.assertEqual(clip_bounds(10_000, 1, None, None), (0, 10_000))
        with self.assertRaisesRegex(ValueError, "explicit start_ms"):
            clip_bounds(120_001, 2, None, None)
        with self.assertRaisesRegex(ValueError, "supplied together"):
            clip_bounds(10_000, 1, 0, None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            source.write_bytes(b"synthetic")
            with self.assertRaisesRegex(FileNotFoundError, "local Whisper checkpoint"):
                build_transcription_evidence(
                    source,
                    root / "output",
                    model_checkpoint=root / "missing.pt",
                    ffmpeg="synthetic",
                    ffprobe="synthetic",
                    whisper="synthetic",
                )

    def test_transcription_uses_explicit_local_model_and_time_locators(self) -> None:
        probe_text = (ROOT / "fixtures" / "video" / "ffprobe-ten-seconds.json").read_text(encoding="utf-8")
        whisper_text = (ROOT / "fixtures" / "video" / "whisper-mixed-zh-en.json").read_text(encoding="utf-8")
        observed_whisper_commands: list[list[str]] = []

        def fake_runner(command, **kwargs):
            if command[0] == "synthetic-ffprobe":
                return subprocess.CompletedProcess(command, 0, probe_text, "")
            if command[0] == "synthetic-ffmpeg":
                Path(command[-1]).write_bytes(b"synthetic bounded wav")
                return subprocess.CompletedProcess(command, 0, "", "")
            observed_whisper_commands.append(command)
            output_dir = Path(command[command.index("--output_dir") + 1])
            (output_dir / "bounded-clip.json").write_text(whisper_text, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            model = root / "local-model.pt"
            source.write_bytes(b"synthetic video")
            model.write_bytes(b"synthetic local checkpoint")
            payload = build_transcription_evidence(
                source,
                root / "evidence",
                model_checkpoint=model,
                start_ms=1000,
                end_ms=9000,
                max_minutes=1,
                runner=fake_runner,
                ffmpeg="synthetic-ffmpeg",
                ffprobe="synthetic-ffprobe",
                whisper="synthetic-whisper",
            )
            self.assertEqual(payload["status"], "succeeded")
            result = payload["results"][0]
            self.assertEqual(result["clip_locator"]["start_ms"], 1000)
            self.assertEqual(result["transcript"]["segments"][0]["start_ms"], 1250)
            self.assertEqual(result["transcript"]["segments"][0]["words"][0]["start_ms"], 1250)
            self.assertEqual(result["model_checkpoint_source"], "explicit_local_path")
            self.assertFalse(result["network_download_requested"])
            self.assertEqual(result["speaker_review_status"], "not_reviewed")
            self.assertEqual(result["adoption_status"], "not_adopted")
            self.assertEqual(len(observed_whisper_commands), 1)
            command = observed_whisper_commands[0]
            self.assertEqual(Path(command[command.index("--model") + 1]), model.resolve())

    def test_transcription_failure_is_not_retried(self) -> None:
        probe_text = (ROOT / "fixtures" / "video" / "ffprobe-ten-seconds.json").read_text(encoding="utf-8")
        whisper_calls = 0

        def fake_runner(command, **kwargs):
            nonlocal whisper_calls
            if command[0] == "synthetic-ffprobe":
                return subprocess.CompletedProcess(command, 0, probe_text, "")
            if command[0] == "synthetic-ffmpeg":
                Path(command[-1]).write_bytes(b"synthetic bounded wav")
                return subprocess.CompletedProcess(command, 0, "", "")
            whisper_calls += 1
            return subprocess.CompletedProcess(command, 7, "", "synthetic Whisper failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            model = root / "local-model.pt"
            source.write_bytes(b"synthetic video")
            model.write_bytes(b"synthetic model")
            payload = build_transcription_evidence(
                source,
                root / "evidence",
                model_checkpoint=model,
                max_minutes=1,
                runner=fake_runner,
                ffmpeg="synthetic-ffmpeg",
                ffprobe="synthetic-ffprobe",
                whisper="synthetic-whisper",
            )
        result = payload["results"][0]
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(whisper_calls, 1)
        self.assertEqual(result["failure_ledger"][0]["stage"], "transcription")
        self.assertEqual(result["failure_ledger"][0]["retry_status"], "not_retried")

    def test_transcription_timeout_writes_failure_ledger_without_retry(self) -> None:
        calls = 0

        def timeout_runner(command, **kwargs):
            nonlocal calls
            calls += 1
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
            model = root / "local-model.pt"
            output = root / "evidence"
            source.write_bytes(b"synthetic video")
            model.write_bytes(b"synthetic model")
            payload = build_transcription_evidence(
                source,
                output,
                model_checkpoint=model,
                runner=timeout_runner,
                ffmpeg="synthetic",
                ffprobe="synthetic",
                whisper="synthetic",
            )
            self.assertTrue((output / "transcription-evidence.json").is_file())
        self.assertEqual(calls, 1)
        self.assertEqual(payload["results"][0]["failure_ledger"][0]["stage"], "duration_probe_timeout")
        self.assertEqual(payload["results"][0]["recovery"]["resume_supported"], False)


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
    def test_skill_version_has_one_consistent_repository_source(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "methods" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(SKILL_VERSION, version)
        self.assertEqual(project["project"]["version"], version)
        self.assertEqual(registry["skill_version"], version)

    def test_all_method_manifests_have_registered_versions(self) -> None:
        registry = json.loads((ROOT / "methods" / "registry.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "contracts" / "method-manifest.schema.json").read_text(encoding="utf-8"))
        required = set(schema["required"])
        allowed = set(schema["properties"])
        validation_statuses = set(schema["properties"]["validation"]["properties"]["status"]["enum"])
        for item in registry["methods"]:
            manifest = json.loads((ROOT / "methods" / item["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(required - manifest.keys(), set())
            self.assertEqual(set(manifest) - allowed, set(), item["manifest"])
            self.assertEqual(manifest["method_id"], item["method_id"])
            self.assertEqual(manifest["version"], item["version"])
            self.assertIn(manifest["validation"]["status"], validation_statuses, item["manifest"])
        validation = validate_method_manifests(ROOT)
        self.assertTrue(validation["valid"], validation["errors"])

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
        self.assertIn("ocr", completed.stdout)
        self.assertIn("pdf", completed.stdout)
        self.assertIn("video", completed.stdout)
        self.assertIn("transcribe", completed.stdout)


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
