from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from assess_incremental_discovery import assess_incremental_discovery  # noqa: E402
from compile_incremental_discovery import compile_incremental_discovery  # noqa: E402
from prepare_incremental_discovery import prepare_incremental_discovery  # noqa: E402
from rebase_incremental_discovery import rebase_incremental_discovery  # noqa: E402
from render_report import apply_increment_policy, render_html, render_markdown  # noqa: E402


FIXTURE = ROOT / "fixtures" / "incremental-discovery"


def load(name: str) -> dict:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def compile_candidates(candidates: dict) -> dict:
    evidence = load("evidence-cards.json")
    baseline = {
        "contract_version": "data-lens-incremental-discovery-baseline/0.1",
        "decision_question": candidates["decision_question"],
        "native_first_pass": deepcopy(candidates["native_first_pass"]),
    }
    brief = prepare_incremental_discovery(baseline, evidence, FIXTURE)
    return compile_incremental_discovery(candidates, evidence, FIXTURE, brief)


def mark_external_coverage_complete(baseline: dict) -> None:
    retained = baseline["native_first_pass"]["retained_findings"]
    baseline["coverage_review"] = {
        "reviewer_pass": "external-baseline-coverage-pass",
        "status": "complete",
        "material_findings": [
            {"source_locator": f"raw-final/finding/{index}", "baseline_text": text}
            for index, text in enumerate(retained, start=1)
        ],
        "omitted_material_findings": [],
    }


class IncrementalDiscoveryTests(unittest.TestCase):
    def test_prepare_selects_mode_before_candidates_are_generated(self) -> None:
        brief = prepare_incremental_discovery(load("baseline.json"), load("evidence-cards.json"), FIXTURE)
        self.assertEqual(brief["recommended_mode"], "adversarial_augmentation")
        self.assertEqual(brief["missing_baseline_capabilities"], [])
        self.assertIn("do not rerun full discovery", brief["generation_brief"]["objective"])
        self.assertFalse(brief["analysis_increment_claimed"])

    def test_compiler_preserves_e0_and_rejects_rephrasing(self) -> None:
        candidates = load("candidates.json")
        ledger = compile_candidates(candidates)
        self.assertEqual(ledger["baseline"]["snapshot"], candidates["native_first_pass"])
        self.assertEqual(ledger["search"]["recommended_mode"], "adversarial_augmentation")
        by_id = {item["candidate_id"]: item for item in ledger["candidates"]}
        self.assertTrue(by_id["E1-METRIC"]["eligible_for_review"])
        self.assertTrue(by_id["E1-SELECTION"]["eligible_for_review"])
        self.assertFalse(by_id["E1-REPHRASE"]["eligible_for_review"])
        self.assertIn(
            "structural_change does not change the baseline assumption",
            by_id["E1-REPHRASE"]["contract_errors"],
        )
        self.assertFalse(ledger["summary"]["analysis_increment_claimed"])

    def test_measured_holdout_review_can_validate_a_direct_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        assessment = assess_incremental_discovery(ledger, load("reviews-v0.2.json"))
        by_id = {item["candidate_id"]: item for item in assessment["candidate_assessments"]}
        self.assertEqual(by_id["E1-METRIC"]["outcome"], "validated_increment")
        self.assertEqual(assessment["summary"]["overall_result"], "validated_increment")
        self.assertTrue(assessment["summary"]["analysis_increment_claimed"])
        self.assertFalse(assessment["summary"]["relative_to_raw_model_claimed"])

    def test_legacy_review_cannot_validate_without_a_measured_experiment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        reviews = load("reviews.json")
        reviews["reviews"] = [deepcopy(reviews["reviews"][0])]
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        self.assertEqual(assessment["summary"]["final_report_mode"], "e0_only")
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])

    def test_generation_and_holdout_evidence_must_be_disjoint(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"][0]["holdout_evidence_refs"] = ["E-GEN-1"]
        ledger = compile_candidates(candidates)
        item = ledger["candidates"][0]
        self.assertFalse(item["eligible_for_review"])
        self.assertTrue(any("must be disjoint" in error for error in item["contract_errors"]))

    def test_holdout_evidence_must_also_be_disjoint_from_e0(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        candidates["candidates"][0]["holdout_evidence_refs"] = ["E-GEN-2"]
        ledger = compile_candidates(candidates)
        self.assertFalse(ledger["candidates"][0]["eligible_for_review"])
        self.assertTrue(any("must be disjoint" in error for error in ledger["candidates"][0]["contract_errors"]))

    def test_holdout_alias_with_a_different_id_is_not_independent(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        evidence = load("evidence-cards.json")
        evidence["cards"][2].update({
            "source": evidence["cards"][0]["source"],
            "source_sha256": evidence["cards"][0]["source_sha256"],
            "locator": deepcopy(evidence["cards"][0]["locator"]),
            "unit_id": evidence["cards"][0]["unit_id"],
            "independence_group": evidence["cards"][0]["independence_group"],
        })
        baseline = {
            "contract_version": "data-lens-incremental-discovery-baseline/0.1",
            "decision_question": candidates["decision_question"],
            "native_first_pass": deepcopy(candidates["native_first_pass"]),
        }
        brief = prepare_incremental_discovery(baseline, evidence, FIXTURE)
        ledger = compile_incremental_discovery(candidates, evidence, FIXTURE, brief)
        item = ledger["candidates"][0]
        self.assertFalse(item["eligible_for_review"])
        self.assertTrue(any("reuse" in error for error in item["contract_errors"]))

    def test_prohibited_or_partial_test_cannot_qualify(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        candidates["candidates"][0]["discriminating_test"]["safety_status"] = "prohibited"
        ledger = compile_candidates(candidates)
        self.assertFalse(ledger["candidates"][0]["eligible_for_review"])
        candidates["candidates"][0]["discriminating_test"]["safety_status"] = "safe"
        candidates["candidates"][0]["discriminating_test"]["directness"] = "partial"
        ledger = compile_candidates(candidates)
        self.assertFalse(ledger["candidates"][0]["eligible_for_review"])

    def test_incomplete_e0_switches_back_to_full_discovery(self) -> None:
        candidates = load("candidates.json")
        candidates["native_first_pass"]["predictions"] = []
        baseline = load("baseline.json")
        baseline["native_first_pass"] = deepcopy(candidates["native_first_pass"])
        brief = prepare_incremental_discovery(baseline, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(brief["recommended_mode"], "full_discovery")
        self.assertIn("prediction_present", brief["missing_baseline_capabilities"])
        ledger = compile_incremental_discovery(
            candidates,
            load("evidence-cards.json"),
            FIXTURE,
            brief,
        )
        self.assertEqual(ledger["search"]["recommended_mode"], "full_discovery")
        self.assertEqual(ledger["summary"]["provisional_result"], "baseline_incomplete")
        self.assertEqual(ledger["summary"]["eligible_for_review_count"], 0)

    def test_empty_candidate_search_admits_no_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = []
        ledger = compile_candidates(candidates)
        self.assertEqual(ledger["summary"]["provisional_result"], "no_increment_detected")
        assessment = assess_incremental_discovery(ledger, load("no-increment-reviews.json"))
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])

    def test_e0_cannot_change_after_preparation(self) -> None:
        baseline = load("baseline.json")
        brief = prepare_incremental_discovery(baseline, load("evidence-cards.json"), FIXTURE)
        candidates = load("candidates.json")
        candidates["native_first_pass"]["core_problem"] = "候选生成后改写的基线"
        ledger = compile_incremental_discovery(
            candidates,
            load("evidence-cards.json"),
            FIXTURE,
            brief,
        )
        self.assertFalse(ledger["search"]["contract_valid"])
        self.assertIn(
            "native_first_pass differs from prepared baseline brief",
            ledger["search"]["contract_errors"],
        )
        self.assertEqual(ledger["summary"]["eligible_for_review_count"], 0)

    def test_test_target_must_match_the_candidate_core_mechanism(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        candidates["candidates"][0]["discriminating_test"]["target_mechanism"] = "模板是否提高互动"
        ledger = compile_candidates(candidates)
        item = ledger["candidates"][0]
        self.assertFalse(item["eligible_for_review"])
        self.assertIn(
            "discriminating_test.target_mechanism must match candidate core_mechanism",
            item["contract_errors"],
        )

    def test_complete_review_can_return_no_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [candidates["candidates"][2]]
        candidates["search"]["operators_attempted"] = ["selection_process"]
        ledger = compile_candidates(candidates)
        reviews = load("no-increment-reviews.json")
        reviews["reviews"] = [{
            "candidate_id": "E1-SELECTION",
            "reviewer_pass": "holdout-pass-2",
            "structure_status": "same",
            "prediction_status": "same",
            "novelty_status": "already_in_e0",
            "mechanism_test_status": "direct",
            "holdout_status": "not_tested",
            "decision_status": "no_change",
            "review_evidence_refs": [],
            "rationale": "复核后发现候选只是把发布量影响换了一种说法。",
        }]
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])
        self.assertEqual(assessment["baseline_snapshot"], candidates["native_first_pass"])

    def test_candidate_already_present_anywhere_in_e0_is_not_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        candidates["native_first_pass"]["retained_findings"].append(candidates["candidates"][0]["claim"])
        ledger = compile_candidates(candidates)
        reviews = load("reviews.json")
        reviews["reviews"] = [deepcopy(reviews["reviews"][0])]
        reviews["reviews"][0]["novelty_status"] = "already_in_e0"
        reviews["reviews"][0]["rationale"] = "该判断已经明确出现在裸模型首轮保留发现中。"
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])

    def test_external_raw_final_is_the_strict_comparison_baseline(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        frozen_ledger = compile_candidates(candidates)
        frozen_candidates = deepcopy(frozen_ledger["candidates"])
        external = load("baseline.json")
        external["native_first_pass"]["baseline_id"] = "raw-codex-final-A"
        external["native_first_pass"]["capture_mode"] = "external_raw_baseline"
        external["native_first_pass"]["retained_findings"].append(
            candidates["candidates"][0]["claim"]
        )
        mark_external_coverage_complete(external)
        ledger = rebase_incremental_discovery(
            frozen_ledger, external, load("evidence-cards.json"), FIXTURE
        )
        self.assertEqual(ledger["candidates"], frozen_candidates)
        self.assertEqual(
            ledger["generation_baseline"]["snapshot"]["capture_mode"],
            "pre_engine_first_pass",
        )
        reviews = load("reviews-v0.2.json")
        reviews["reviews"][0]["novelty_status"] = "already_in_e0"
        reviews["reviews"][0]["rationale"] = "Skill 候选已经出现在真实裸 Codex 最终结果中。"
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(
            assessment["baseline_snapshot"]["capture_mode"],
            "external_raw_baseline",
        )
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertEqual(assessment["summary"]["final_report_mode"], "e0_only")
        self.assertEqual(assessment["summary"]["reader_notice"], "本轮没有分析增量。")
        self.assertFalse(assessment["summary"]["relative_to_raw_model_claimed"])

    def test_exact_external_prediction_overlap_cannot_be_claimed_as_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        frozen = compile_candidates(candidates)
        external = load("baseline.json")
        external["native_first_pass"]["capture_mode"] = "external_raw_baseline"
        external["native_first_pass"]["predictions"] = [
            candidates["candidates"][0]["discriminating_test"]["e1_prediction"]
        ]
        mark_external_coverage_complete(external)
        rebased = rebase_incremental_discovery(
            frozen, external, load("evidence-cards.json"), FIXTURE
        )
        assessment = assess_incremental_discovery(rebased, load("reviews-v0.2.json"))
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertFalse(assessment["summary"]["relative_to_raw_model_claimed"])

    def test_incomplete_external_baseline_coverage_forces_e0_only(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        frozen = compile_candidates(candidates)
        external = load("baseline.json")
        external["native_first_pass"]["capture_mode"] = "external_raw_baseline"
        rebased = rebase_incremental_discovery(
            frozen, external, load("evidence-cards.json"), FIXTURE
        )
        assessment = assess_incremental_discovery(rebased, load("reviews-v0.2.json"))
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        self.assertEqual(assessment["summary"]["final_report_mode"], "e0_only")

    def test_posthoc_executable_predicate_change_invalidates_review(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        reviews = load("reviews-v0.2.json")
        reviews["experiment_results"][0]["execution_binding"]["hypothesis_predictions"]["E1-METRIC"] = {
            "operator": "gt",
            "value": -999,
        }
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        item = assessment["candidate_assessments"][0]
        self.assertIn(
            "experiment E1 predicate differs from the frozen candidate test",
            item["review_errors"],
        )

    def test_malformed_execution_binding_is_reported_without_crashing(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        reviews = load("reviews-v0.2.json")
        execution = reviews["experiment_results"][0]["execution_binding"]
        execution["data_evidence_refs"] = ["HOLDOUT-001", 7]
        execution["hypothesis_predictions"] = ["not-an-object"]
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        errors = assessment["candidate_assessments"][0]["review_errors"]
        self.assertIn(
            "experiment execution_binding.data_evidence_refs must contain non-empty strings",
            errors,
        )
        self.assertIn("experiment hypothesis_predictions must be an object", errors)

    def test_tangential_experiment_cannot_create_increment(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        reviews = load("reviews.json")
        reviews["reviews"] = [deepcopy(reviews["reviews"][0])]
        reviews["reviews"][0]["mechanism_test_status"] = "tangential"
        reviews["reviews"][0]["rationale"] = "实验比较原创与模板，但没有隔离反馈来源，不能检验反馈污染。"
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])

    def test_review_must_be_a_different_pass(self) -> None:
        ledger = compile_candidates(load("candidates.json"))
        reviews = load("reviews.json")
        reviews["reviews"][0]["reviewer_pass"] = "candidate-pass-1"
        assessment = assess_incremental_discovery(ledger, reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        self.assertEqual(assessment["summary"]["final_report_mode"], "e0_only")
        self.assertEqual(
            assessment["summary"]["reader_notice"],
            "本轮没有分析增量：增量评审未完成或无效。",
        )
        self.assertFalse(assessment["summary"]["analysis_increment_claimed"])
        item = next(row for row in assessment["candidate_assessments"] if row["candidate_id"] == "E1-METRIC")
        self.assertIn("reviewer_pass must differ from candidate_generation_pass", item["review_errors"])

    def test_e0_only_assessment_controls_the_report_boundary(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
        candidates["search"]["operators_attempted"] = ["metric_role"]
        ledger = compile_candidates(candidates)
        reviews = load("reviews-v0.2.json")
        reviews["reviews"][0]["reviewer_pass"] = "candidate-pass-1"
        assessment = assess_incremental_discovery(ledger, reviews)
        report = {
            "scope": {"decision_question": candidates["decision_question"]},
            "title": "测试报告",
            "subtitle": "",
            "findings": [{"id": "F-E1", "increment_candidate_id": "E1-METRIC"}],
        }
        with self.assertRaisesRegex(ValueError, "excluded by assessment"):
            apply_increment_policy(report, assessment)

        report["findings"] = [{"id": "F-E0"}]
        report["baseline_retention"] = [
            {
                "baseline_finding_id": f"E0-R{index:03d}",
                "status": "retained",
                "report_finding_ids": ["F-E0"],
                "evidence_ids": [],
                "rationale": "E0 发现继续保留在最终报告中。",
            }
            for index, _ in enumerate(
                assessment["baseline_snapshot"]["retained_findings"], start=1
            )
        ]
        governed = apply_increment_policy(report, assessment)
        markdown = render_markdown(governed)
        html = render_html(governed, "")
        self.assertEqual(
            governed["_incremental_discovery"]["reader_notice"],
            "本轮没有分析增量：增量评审未完成或无效。",
        )
        self.assertNotIn("本轮没有分析增量", markdown)
        self.assertNotIn("本轮没有分析增量", html)

    def test_final_report_cannot_silently_drop_a_retained_e0_finding(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = []
        assessment = assess_incremental_discovery(
            compile_candidates(candidates), load("no-increment-reviews.json")
        )
        report = {
            "scope": {"decision_question": candidates["decision_question"]},
            "findings": [{"id": "F-E0"}],
            "evidence": [],
            "baseline_retention": [
                {
                    "baseline_finding_id": "E0-R001",
                    "status": "retained",
                    "report_finding_ids": ["F-E0"],
                    "evidence_ids": [],
                    "rationale": "只映射了第一项。",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "missing:E0-R002,E0-R003"):
            apply_increment_policy(report, assessment)

    def test_superseded_e0_finding_requires_a_replacement_and_evidence(self) -> None:
        candidates = load("candidates.json")
        candidates["candidates"] = []
        assessment = assess_incremental_discovery(
            compile_candidates(candidates), load("no-increment-reviews.json")
        )
        report = {
            "scope": {"decision_question": candidates["decision_question"]},
            "findings": [{"id": "F-REPLACEMENT"}],
            "evidence": [{"id": "E-NEW"}],
            "baseline_retention": [
                {
                    "baseline_finding_id": f"E0-R{index:03d}",
                    "status": "superseded" if index == 2 else "retained",
                    "report_finding_ids": ["F-REPLACEMENT"],
                    "evidence_ids": ["E-NEW"] if index == 2 else [],
                    "rationale": "后续证据替代原判断。" if index == 2 else "继续保留。",
                }
                for index in range(1, 4)
            ],
        }
        governed = apply_increment_policy(report, assessment)
        self.assertTrue(
            governed["_incremental_discovery"]["baseline_preservation"]["complete"]
        )


if __name__ == "__main__":
    unittest.main()
