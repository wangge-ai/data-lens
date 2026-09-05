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
from run_hypothesis_experiment import run_hypothesis_experiment  # noqa: E402


EXPERIMENT_FIXTURE = ROOT / "fixtures" / "hypothesis-experiment"
INCREMENT_FIXTURE = ROOT / "fixtures" / "incremental-discovery"


def load(folder: Path, name: str) -> dict:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def one_candidate_ledger() -> dict:
    candidates = load(INCREMENT_FIXTURE, "candidates.json")
    candidates["candidates"] = [deepcopy(candidates["candidates"][0])]
    candidates["search"]["operators_attempted"] = ["metric_role"]
    evidence = load(INCREMENT_FIXTURE, "evidence-cards.json")
    baseline = {
        "contract_version": "data-lens-incremental-discovery-baseline/0.1",
        "decision_question": candidates["decision_question"],
        "native_first_pass": deepcopy(candidates["native_first_pass"]),
    }
    brief = prepare_incremental_discovery(baseline, evidence, INCREMENT_FIXTURE)
    return compile_incremental_discovery(candidates, evidence, INCREMENT_FIXTURE, brief)


def measured_review(experiment_result: dict) -> dict:
    return {
        "contract_version": "data-lens-incremental-discovery-reviews/0.2",
        "decision_question": "这套方法真正依赖什么增长逻辑，最关键的问题是什么？",
        "experiment_results": [experiment_result],
        "reviews": [
            {
                "candidate_id": "E1-METRIC",
                "reviewer_pass": "holdout-pass-python-1",
                "structure_status": "distinct",
                "prediction_status": "divergent",
                "novelty_status": "new_to_e0",
                "mechanism_test_status": "direct",
                "decision_status": "changes",
                "experiment_result_id": experiment_result["experiment_id"],
                "review_evidence_refs": ["E-HOLD-1"],
                "rationale": "独立复核确认实验直接比较反馈来源，结果方向由 Python 计算。",
            }
        ],
    }


class HypothesisExperimentTests(unittest.TestCase):
    def test_intraday_claim_is_unverifiable_with_daily_data(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "wave-granularity-spec.json")
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        component = result["dimensions"]["time"]["components"][0]
        self.assertEqual(component["status"], "unverifiable")
        self.assertIn("coarser", component["reason"])
        self.assertIsNone(result["summary"]["total_label"])

    def test_intraday_time_is_scored_when_five_minute_data_exists(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "wave-granularity-spec.json")
        spec["experiment_id"] = "WAVE-GRAIN-2"
        spec["data_source"] = {
            "rows": [
                {"timestamp": "2025-06-06T13:55:00", "close": 3378},
                {"timestamp": "2025-06-06T14:00:00", "close": 3386},
                {"timestamp": "2025-06-06T14:05:00", "close": 3382},
            ],
            "granularity": "intraday_5m",
            "time_field": "timestamp",
        }
        component = spec["components"][0]
        component["measurement"] = {"kind": "time_of_max", "field": "close"}
        component["expectation"] = {
            "operator": "between",
            "value": ["2025-06-06T13:55:00", "2025-06-06T14:05:00"],
        }
        result = run_hypothesis_experiment(spec)
        component_result = result["dimensions"]["time"]["components"][0]
        self.assertEqual(component_result["status"], "supported")
        self.assertEqual(component_result["measurement"]["value"], "2025-06-06T14:00:00")

    def test_composite_claim_keeps_each_dimension_outcome(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "wave-composite-spec.json")
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        by_dimension = {
            name: detail["components"][0]["status"]
            for name, detail in result["dimensions"].items()
            if detail["components"]
        }
        self.assertEqual(by_dimension["direction"], "supported")
        self.assertEqual(by_dimension["time"], "supported")
        self.assertEqual(by_dimension["point"], "contradicted")
        self.assertEqual(by_dimension["path"], "contradicted")
        self.assertEqual(by_dimension["invalidation"], "triggered")
        self.assertIsNone(result["summary"]["total_label"])

    def test_evaluation_window_cannot_expand_to_repair_a_forecast(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "wave-window-spec.json")
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        component = result["dimensions"]["direction"]["components"][0]
        self.assertEqual(component["status"], "contradicted")
        self.assertEqual(component["window"]["excluded_outside_window_count"], 2)
        self.assertFalse(component["window"]["window_expanded"])

    def test_direct_comparison_computes_support_for_e1(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json")
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        self.assertEqual(result["execution_status"], "completed")
        self.assertTrue(result["direct_binding"]["valid"])
        self.assertAlmostEqual(result["measurement"]["value"], 0.5)
        self.assertEqual(result["supported_hypothesis_ids"], ["E1-METRIC"])
        self.assertEqual(result["evidence_direction"], "supports_e1")

    def test_tangential_changed_variable_is_rejected_before_measurement(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json")
        spec["changed_or_isolated_variable"] = "内容模板"
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        self.assertEqual(result["execution_status"], "rejected_misaligned")
        self.assertFalse(result["direct_binding"]["valid"])
        self.assertEqual(result["evidence_direction"], "not_tested")

    def test_lagged_signal_can_directly_distinguish_competing_predictions(self) -> None:
        spec = {
            "contract_version": "data-lens-hypothesis-experiment/0.1",
            "experiment_id": "LAG-1",
            "decision_question": "信号是同步噪声还是领先结果？",
            "mode": "hypothesis_comparison",
            "candidate_id": "E1-LAG",
            "data_evidence_refs": ["E-HOLD-LAG"],
            "candidate_core_mechanism": "信号变化领先一期结果变化",
            "target_mechanism": "信号变化领先一期结果变化",
            "mechanism_variable": "领先一期信号",
            "changed_or_isolated_variable": "领先一期信号",
            "measurement_window_claim": "完整四期",
            "distinguishing_observation": "信号与下一期结果的相关系数",
            "baseline_hypothesis_id": "E0",
            "candidate_hypothesis_id": "E1-LAG",
            "hypotheses": [
                {"hypothesis_id": "E0", "statement": "没有领先关系", "prediction": {"operator": "abs_lte", "value": 0.2}},
                {"hypothesis_id": "E1-LAG", "statement": "存在明显领先关系", "prediction": {"operator": "gt", "value": 0.8}},
            ],
            "data_source": {
                "rows": [
                    {"date": "2026-01-01", "signal": 1, "outcome": 0},
                    {"date": "2026-01-02", "signal": 2, "outcome": 2},
                    {"date": "2026-01-03", "signal": 3, "outcome": 4},
                    {"date": "2026-01-04", "signal": 4, "outcome": 6},
                ],
                "granularity": "daily",
                "time_field": "date",
            },
            "required_granularity": "daily",
            "evaluation_window": {"start": "2026-01-01", "end": "2026-01-04"},
            "measurement": {"kind": "lagged_pearson", "x_field": "signal", "y_field": "outcome", "lag": 1},
        }
        result = run_hypothesis_experiment(spec)
        self.assertEqual(result["evidence_direction"], "supports_e1")
        self.assertAlmostEqual(result["measurement"]["value"], 1.0)

    def test_group_sample_size_counts_only_nonmissing_measurements(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json")
        spec["data_source"].pop("path")
        spec["data_source"]["rows"] = [
            {"date": "2026-01-01", "feedback_origin": "natural", "retention_30d": 0.8},
            {"date": "2026-01-02", "feedback_origin": "natural", "retention_30d": ""},
            {"date": "2026-01-01", "feedback_origin": "shaped", "retention_30d": 0.2},
        ]
        result = run_hypothesis_experiment(spec)
        self.assertEqual(result["measurement"]["group_a"]["n"], 1)
        self.assertEqual(result["measurement"]["group_b"]["n"], 1)

    def test_walk_forward_interval_uses_only_prior_events(self) -> None:
        spec = {
            "contract_version": "data-lens-hypothesis-experiment/0.1",
            "experiment_id": "CYCLE-WF-1",
            "decision_question": "历史间隔能否前推下一次事件？",
            "mode": "atomic_claims",
            "data_source": {
                "rows": [
                    {"date": value, "event": 1}
                    for value in ("2026-01-01", "2026-01-06", "2026-01-11", "2026-01-16", "2026-01-21", "2026-01-26")
                ],
                "granularity": "daily",
                "time_field": "date",
            },
            "declared_dimensions": ["time"],
            "components": [
                {
                    "component_id": "WF-INTERVAL",
                    "dimension": "time",
                    "statement": "只用过去间隔预测下一次事件，平均绝对误差不超过一天",
                    "required_granularity": "daily",
                    "evaluation_window": {"start": "2026-01-01", "end": "2026-01-26"},
                    "measurement": {"kind": "walk_forward_interval_mae", "event_field": "event", "minimum_history": 3},
                    "expectation": {"operator": "lte", "value": 1},
                }
            ],
        }
        result = run_hypothesis_experiment(spec)
        component = result["dimensions"]["time"]["components"][0]
        self.assertEqual(component["status"], "supported")
        self.assertEqual(component["measurement"]["prediction_count"], 2)
        self.assertEqual(component["measurement"]["value"], 0.0)

    def test_review_v02_derives_holdout_direction_from_python_result(self) -> None:
        result = run_hypothesis_experiment(
            load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json"),
            EXPERIMENT_FIXTURE,
        )
        assessment = assess_incremental_discovery(one_candidate_ledger(), measured_review(result))
        self.assertEqual(assessment["summary"]["overall_result"], "validated_increment")
        self.assertTrue(assessment["summary"]["analysis_increment_claimed"])
        self.assertIsNone(assessment["summary"]["reader_notice"])
        self.assertEqual(
            assessment["candidate_assessments"][0]["review"]["holdout_status"],
            "supports_e1",
        )

    def test_measured_review_fixture_is_executable(self) -> None:
        reviews = load(INCREMENT_FIXTURE, "reviews-v0.2.json")
        assessment = assess_incremental_discovery(one_candidate_ledger(), reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "validated_increment")

    def test_review_v02_rejects_a_model_supplied_total_direction(self) -> None:
        result = run_hypothesis_experiment(
            load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json"),
            EXPERIMENT_FIXTURE,
        )
        reviews = measured_review(result)
        reviews["reviews"][0]["holdout_status"] = "supports_e1"
        assessment = assess_incremental_discovery(one_candidate_ledger(), reviews)
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        self.assertIn(
            "review contract 0.2 derives holdout_status from Python; it must not be supplied",
            assessment["candidate_assessments"][0]["review_errors"],
        )

    def test_review_v02_rejects_prediction_drift_after_candidate_freeze(self) -> None:
        result = run_hypothesis_experiment(
            load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json"),
            EXPERIMENT_FIXTURE,
        )
        result["hypotheses"][1]["statement"] = "看到结果后改写的新预测"
        assessment = assess_incremental_discovery(one_candidate_ledger(), measured_review(result))
        self.assertEqual(assessment["summary"]["overall_result"], "review_incomplete")
        self.assertIn(
            "experiment E1 prediction differs from the frozen candidate prediction",
            assessment["candidate_assessments"][0]["review_errors"],
        )

    def test_no_increment_has_an_explicit_reader_notice(self) -> None:
        spec = load(EXPERIMENT_FIXTURE, "feedback-comparison-spec.json")
        spec["data_source"].pop("path")
        spec["data_source"]["rows"] = [
            {"date": "2026-01-01", "feedback_origin": "natural", "retention_30d": 0.55},
            {"date": "2026-01-02", "feedback_origin": "natural", "retention_30d": 0.50},
            {"date": "2026-01-01", "feedback_origin": "shaped", "retention_30d": 0.50},
            {"date": "2026-01-02", "feedback_origin": "shaped", "retention_30d": 0.50},
        ]
        result = run_hypothesis_experiment(spec, EXPERIMENT_FIXTURE)
        self.assertEqual(result["evidence_direction"], "supports_e0")
        assessment = assess_incremental_discovery(one_candidate_ledger(), measured_review(result))
        self.assertEqual(assessment["summary"]["overall_result"], "no_increment")
        self.assertEqual(assessment["summary"]["reader_notice"], "本轮没有分析增量。")


if __name__ == "__main__":
    unittest.main()
