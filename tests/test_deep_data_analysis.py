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

from compile_deep_analysis_question import compile_deep_analysis_question  # noqa: E402
from run_hypothesis_experiment import run_hypothesis_experiment  # noqa: E402


FIXTURE = ROOT / "fixtures" / "deep-analysis-question"


def load(name: str) -> dict:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def atomic_spec(measurement: dict, rows: list[dict], expectation: dict) -> dict:
    return {
        "contract_version": "data-lens-hypothesis-experiment/0.1",
        "experiment_id": "DEEP-PROBE-1",
        "decision_question": "候选解释在时间、分群或对照上是否成立？",
        "mode": "atomic_claims",
        "data_source": {
            "rows": rows,
            "granularity": "daily",
            "time_field": "date",
        },
        "declared_dimensions": ["path"],
        "components": [
            {
                "component_id": "PROBE-1",
                "dimension": "path",
                "statement": "执行预先声明的深度数据探针",
                "required_granularity": "daily",
                "evaluation_window": {"start": "2026-01-01", "end": "2026-01-31"},
                "measurement": measurement,
                "expectation": expectation,
            }
        ],
    }


class DeepAnalysisQuestionTests(unittest.TestCase):
    def test_observational_question_preserves_deep_layers_but_blocks_causal_claim(self) -> None:
        result = compile_deep_analysis_question(
            load("profit-causal-question.json"), load("evidence-cards.json"), FIXTURE
        )
        self.assertEqual(result["contract_status"], "compiled")
        self.assertEqual(result["analysis_layers"]["measurement"]["status"], "ready")
        self.assertEqual(result["analysis_layers"]["temporal"]["status"], "ready")
        self.assertEqual(result["analysis_layers"]["heterogeneity"]["status"], "conditional")
        self.assertEqual(result["analysis_layers"]["mechanism"]["status"], "ready")
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "blocked")
        self.assertEqual(result["claim_permissions"]["causal"], "blocked")
        self.assertIsNone(result["summary"]["overall_depth_label"])

    def test_compare_requires_a_declared_grouping_dimension(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "compare"
        spec.pop("causal_design")
        spec["scope"]["segments"] = []
        spec["data_readiness"]["comparison_groups"] = False
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["heterogeneity"]["status"], "conditional")
        self.assertIn("heterogeneity", result["summary"]["required_layers"])

    def test_complete_randomized_design_can_reach_causal_readiness(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {"status": "supported", "evidence_refs": ["EV-ASSIGNMENT-CHECK-01"]}
        }
        design["known_confounders"] = []
        design["assumptions"] = []
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "ready")
        self.assertEqual(result["claim_permissions"]["causal"], "allowed")

    def test_design_evidence_cannot_be_reused_for_a_different_causal_question(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {"status": "supported", "evidence_refs": ["EV-ASSIGNMENT-CHECK-01"]}
        }
        design["known_confounders"] = []
        design["assumptions"] = []
        design["intervention"] = "把商品价格提高10%"
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["contract_status"], "invalid")
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "blocked")
        self.assertTrue(any("not bound" in error for error in result["errors"]))

    def test_time_prediction_rejects_random_split(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "predict"
        spec.pop("causal_design")
        spec["prediction_design"] = {
            "target": "next-month front profit",
            "horizon": "next month",
            "horizon_steps": 1,
            "horizon_unit": "month",
            "cutoff": "2024-09-30",
            "cutoff_mode": "fixed_holdout",
            "validation": "random_split",
            "metric": "MAE",
            "baseline_model": "last value",
            "baseline_kind": "last_observation",
            "baseline_model_id": "last",
            "minimum_history": 3,
            "minimum_improvement": 0.05,
            "uncertainty_method": "circular_block_bootstrap",
            "confidence_level": 0.95,
            "bootstrap_replicates": 300,
            "bootstrap_seed": 17,
            "block_length": 1,
            "minimum_origins": 5,
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"}
            ],
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["predictive"]["status"], "blocked")
        self.assertTrue(result["warnings"])

    def test_uncertain_measurement_cannot_allow_association_or_prediction(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "predict"
        spec.pop("causal_design")
        spec["data_readiness"]["stable_measurement"] = "uncertain"
        spec["prediction_design"] = {
            "target": "next-month front profit",
            "horizon": "next month",
            "horizon_steps": 1,
            "horizon_unit": "month",
            "cutoff": "2024-09-30",
            "cutoff_mode": "rolling_origin",
            "validation": "rolling_origin",
            "metric": "MAE",
            "baseline_model": "last value",
            "baseline_kind": "last_observation",
            "baseline_model_id": "last",
            "minimum_history": 3,
            "minimum_improvement": 0.05,
            "uncertainty_method": "circular_block_bootstrap",
            "confidence_level": 0.95,
            "bootstrap_replicates": 300,
            "bootstrap_seed": 17,
            "block_length": 1,
            "minimum_origins": 5,
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
            ],
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["claim_permissions"]["association"], "conditional")
        self.assertEqual(result["claim_permissions"]["predictive"], "conditional")

    def test_action_choice_without_value_costs_or_threshold_stays_conditional(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "choose_action"
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {"status": "supported", "evidence_refs": ["EV-ASSIGNMENT-CHECK-01"]}
        }
        design["known_confounders"] = []
        design["assumptions"] = []
        spec["decision_design"] = {
            "evidence_basis": "causal_effect",
            "target": "是否降低推广占比",
            "actor": "运营负责人",
            "action_options": ["降低推广", "维持推广"],
            "utility_metric": "",
            "costs": [],
            "constraints": [],
            "decision_threshold": "",
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["decision"]["status"], "conditional")
        self.assertEqual(result["claim_permissions"]["decision"], "conditional")

    def test_prediction_based_decision_does_not_require_causal_identification(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "choose_action"
        spec.pop("causal_design")
        spec["prediction_design"] = {
            "target": "next-month stockout risk",
            "horizon": "next month",
            "horizon_steps": 1,
            "horizon_unit": "month",
            "cutoff": "2024-09-30",
            "cutoff_mode": "rolling_origin",
            "validation": "rolling_origin",
            "metric": "MAE",
            "baseline_model": "last value",
            "baseline_kind": "last_observation",
            "baseline_model_id": "last",
            "minimum_history": 3,
            "minimum_improvement": 0.05,
            "uncertainty_method": "circular_block_bootstrap",
            "confidence_level": 0.95,
            "bootstrap_replicates": 300,
            "bootstrap_seed": 17,
            "block_length": 1,
            "minimum_origins": 5,
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
            ],
        }
        spec["decision_design"] = {
            "evidence_basis": "prediction",
            "target": "是否补货",
            "actor": "库存负责人",
            "action_options": ["补货", "不补货"],
            "utility_metric": "缺货损失与库存成本之和",
            "costs": ["库存资金占用"],
            "constraints": ["仓容"],
            "decision_threshold": "预测缺货损失大于补货成本",
            "action_field": "action",
            "benefit_field": "avoided_stockout_loss",
            "cost_field": "inventory_cost",
            "baseline_action": "不补货",
            "fallback_action": "不补货",
            "minimum_net_utility": 0,
            "minimum_advantage": 0,
            "constraint_rules": [{"field": "capacity_used", "aggregation": "max", "operator": "lte", "value": 1}],
            "withdrawal_condition": "预测缺货损失不再高于库存成本",
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "not_requested")
        self.assertEqual(result["analysis_layers"]["predictive"]["status"], "ready")
        self.assertEqual(result["analysis_layers"]["decision"]["status"], "ready")
        self.assertEqual(result["claim_permissions"]["decision"], "allowed")
        target = result["analysis_targets"]["predictive"]
        self.assertEqual(target["horizon"], "1 month")
        self.assertEqual(target["cutoff"], "each rolling origin")
        self.assertEqual(target["baseline_model"], "last_observation")

    def test_randomized_label_without_assignment_integrity_is_not_causal_ready(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["known_confounders"] = []
        design["assumptions"] = []
        design.pop("identification_checks", None)
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "conditional")
        self.assertNotEqual(result["claim_permissions"]["causal"], "allowed")

    def test_assignment_integrity_cannot_cite_ordinary_content_evidence(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["known_confounders"] = []
        design["assumptions"] = []
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {"status": "supported", "evidence_refs": ["EV-PROFIT-01"]}
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["contract_status"], "invalid")
        self.assertTrue(any("assignment_integrity evidence has invalid lane" in error for error in result["errors"]))

    def test_randomization_plan_cannot_pose_as_assignment_integrity_result(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["known_confounders"] = []
        design["assumptions"] = []
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {
                "status": "supported", "evidence_refs": ["EV-DESIGN-01"]
            }
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["contract_status"], "invalid")
        self.assertTrue(any("invalid lane" in error for error in result["errors"]))

    def test_question_without_evidence_can_route_but_cannot_allow_causal_claims(self) -> None:
        spec = load("profit-causal-question.json")
        design = spec["causal_design"]
        design["assignment_mechanism"] = "randomized"
        design["identification_strategy"] = "randomized"
        design["estimator"] = "group_mean_difference"
        design["positivity"] = "supported"
        design["confounder_review_status"] = "complete"
        design["known_confounders"] = []
        design["assumptions"] = []
        design["design_evidence_refs"] = ["EV-DESIGN-01"]
        design["identification_checks"] = {
            "assignment_integrity": {"status": "supported", "evidence_refs": ["EV-ASSIGNMENT-CHECK-01"]}
        }
        result = compile_deep_analysis_question(spec)
        self.assertEqual(result["contract_status"], "compiled")
        self.assertEqual(result["analysis_layers"]["causal"]["status"], "conditional")
        self.assertNotEqual(result["claim_permissions"]["causal"], "allowed")
        self.assertTrue(result["warnings"])

    def test_unverified_evidence_cannot_compile_question(self) -> None:
        spec = load("profit-causal-question.json")
        spec["data_readiness"]["evidence_refs"] = ["EV-UNVERIFIED"]
        evidence = load("evidence-cards.json")
        evidence["cards"].append({"id": "EV-UNVERIFIED", "verified": False})
        result = compile_deep_analysis_question(spec, evidence, FIXTURE)
        self.assertEqual(result["contract_status"], "invalid")
        self.assertIn("unverified evidence references:EV-UNVERIFIED", result["errors"])

    def test_unknown_evidence_reference_invalidates_compilation(self) -> None:
        spec = load("profit-causal-question.json")
        spec["data_readiness"]["evidence_refs"] = ["EV-NOT-THERE"]
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["contract_status"], "invalid")
        self.assertIn("unknown evidence references:EV-NOT-THERE", result["errors"])

    def test_honest_heterogeneity_plan_freezes_split_and_confirmation_rules(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "compare"
        spec.pop("causal_design")
        spec.pop("mechanism_design")
        spec["heterogeneity_design"].update({
            "validation_mode": "honest_split", "split_field": "sample_role",
            "discovery_value": "discover", "estimation_value": "estimate",
            "unit_id_field": "store_month_id", "discovery_min_group_n": 10,
            "estimation_min_group_n": 10, "discovery_min_abs_difference": 500,
            "max_selected_subgroups": 4, "minimum_confirmed_subgroups": 2,
            "selection_metric": "absolute_difference",
            "confirmation_rule": "same_direction_and_interval_excludes_zero",
        })
        spec["heterogeneity_design"].pop("minimum_group_n")
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["heterogeneity"]["status"], "ready")
        target = result["analysis_targets"]["heterogeneity"]
        self.assertEqual(target["planned_method"], "honest_subgroup_mean_difference")
        self.assertEqual(target["split_field"], "sample_role")
        self.assertEqual(target["minimum_confirmed_subgroups"], 2)

    def test_prediction_without_uncertainty_design_stays_conditional(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "predict"
        spec.pop("causal_design")
        spec.pop("mechanism_design")
        spec["prediction_design"] = {
            "target": "next month profit", "horizon_steps": 1,
            "horizon_unit": "month", "cutoff_mode": "rolling_origin",
            "validation": "rolling_origin", "metric": "MAE",
            "baseline_kind": "last_observation", "baseline_model_id": "last",
            "minimum_history": 3, "minimum_improvement": 0.05,
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
            ],
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["predictive"]["status"], "conditional")
        self.assertIn(
            "circular-block uncertainty for paired forecast losses",
            result["analysis_layers"]["predictive"]["missing_requirements"],
        )

    def test_logged_policy_plan_freezes_overlap_estimators_and_sensitivity(self) -> None:
        spec = load("profit-causal-question.json")
        spec["objective"] = "choose_action"
        spec.pop("causal_design")
        spec.pop("mechanism_design")
        spec["scope"]["outcome"] = {"name": "净收益", "field": "reward", "unit": "元"}
        spec["decision_design"] = {
            "evidence_basis": "descriptive_rule", "target": "选择日志策略",
            "actor": "运营负责人", "action_options": ["policy_a", "policy_b"],
            "utility_metric": "平均净收益", "costs": ["执行成本"],
            "constraints": ["只适用于日志覆盖人群"],
            "decision_threshold": "优势区间下界超过100",
            "evaluation_mode": "logged_policy", "logged_action_field": "logged_action",
            "bootstrap_unit_field": "customer_id",
            "action_values": ["A", "B"], "reward_field": "reward",
            "propensity_field": "propensity", "baseline_action": "policy_a",
            "fallback_action": "policy_a", "minimum_advantage": 100,
            "estimators": ["ips", "snips"], "primary_estimator": "snips",
            "policy_specs": [
                {"policy_id": "policy_a", "policy_type": "explicit_probabilities", "action_probability_fields": {"A": "pa_a", "B": "pa_b"}},
                {"policy_id": "policy_b", "policy_type": "explicit_probabilities", "action_probability_fields": {"A": "pb_a", "B": "pb_b"}},
            ],
            "minimum_effective_sample_size": 30,
            "maximum_importance_weight": 10,
            "confidence_level": 0.95, "bootstrap_replicates": 500,
            "bootstrap_seed": 29, "weight_clip_grid": [2, 5, 10],
            "propensity_floor_grid": [0.01, 0.05],
            "withdrawal_condition": "重叠不足或策略漂移",
        }
        result = compile_deep_analysis_question(spec, load("evidence-cards.json"), FIXTURE)
        self.assertEqual(result["analysis_layers"]["decision"]["status"], "ready")
        target = result["analysis_targets"]["decision"]
        self.assertEqual(target["planned_method"], "offline_policy_value_sensitivity")
        self.assertEqual(target["primary_estimator"], "snips")
        self.assertEqual(target["weight_clip_grid"], [2, 5, 10])


class DeepDataProbeTests(unittest.TestCase):
    def test_difference_in_differences_keeps_four_cell_counts_and_boundary(self) -> None:
        rows = [
            {"date": "2026-01-01", "group": "treated", "period": "pre", "y": 10},
            {"date": "2026-01-02", "group": "treated", "period": "pre", "y": 11},
            {"date": "2026-01-03", "group": "treated", "period": "post", "y": 18},
            {"date": "2026-01-04", "group": "treated", "period": "post", "y": 19},
            {"date": "2026-01-01", "group": "control", "period": "pre", "y": 10},
            {"date": "2026-01-02", "group": "control", "period": "pre", "y": 12},
            {"date": "2026-01-03", "group": "control", "period": "post", "y": 13},
            {"date": "2026-01-04", "group": "control", "period": "post", "y": 15},
        ]
        measurement = {
            "kind": "difference_in_differences",
            "field": "y",
            "group_field": "group",
            "treated_value": "treated",
            "control_value": "control",
            "period_field": "period",
            "pre_value": "pre",
            "post_value": "post",
        }
        result = run_hypothesis_experiment(atomic_spec(measurement, rows, {"operator": "gt", "value": 4}))
        measured = result["dimensions"]["path"]["components"][0]["measurement"]
        self.assertEqual(measured["value"], 5.0)
        self.assertEqual(measured["cells"]["treated_pre"]["n"], 2)
        self.assertIn("not causal proof", measured["claim_boundary"])

    def test_difference_in_differences_rejects_overlapping_pre_and_post_time(self) -> None:
        rows = [
            {"date": "2026-01-03", "group": "treated", "period": "pre", "y": 10},
            {"date": "2026-01-02", "group": "control", "period": "pre", "y": 10},
            {"date": "2026-01-02", "group": "treated", "period": "post", "y": 12},
            {"date": "2026-01-04", "group": "control", "period": "post", "y": 11},
        ]
        measurement = {
            "kind": "difference_in_differences",
            "field": "y",
            "group_field": "group",
            "treated_value": "treated",
            "control_value": "control",
            "period_field": "period",
            "pre_value": "pre",
            "post_value": "post",
        }
        result = run_hypothesis_experiment(atomic_spec(measurement, rows, {"operator": "gt", "value": 0}))
        component = result["dimensions"]["path"]["components"][0]
        self.assertEqual(component["status"], "unverifiable")
        self.assertIn("pre observation to precede", component["reason"])

    def test_subgroup_probe_exposes_opposite_directions_hidden_by_average(self) -> None:
        rows = [
            {"date": "2026-01-01", "arm": "a", "segment": "new", "y": 10},
            {"date": "2026-01-01", "arm": "b", "segment": "new", "y": 5},
            {"date": "2026-01-01", "arm": "a", "segment": "old", "y": 6},
            {"date": "2026-01-01", "arm": "b", "segment": "old", "y": 8},
        ]
        measurement = {
            "kind": "subgroup_difference_spread",
            "field": "y",
            "group_field": "arm",
            "group_a": "a",
            "group_b": "b",
            "subgroup_field": "segment",
        }
        result = run_hypothesis_experiment(atomic_spec(measurement, rows, {"operator": "gt", "value": 6}))
        measured = result["dimensions"]["path"]["components"][0]["measurement"]
        self.assertEqual(measured["value"], 7.0)
        self.assertTrue(measured["opposite_directions"])
        self.assertEqual(len(measured["subgroup_effects"]), 2)

    def test_rolling_origin_naive_forecast_uses_only_prior_values(self) -> None:
        rows = [
            {"date": "2026-01-01", "y": 10},
            {"date": "2026-01-02", "y": 12},
            {"date": "2026-01-03", "y": 11},
            {"date": "2026-01-04", "y": 15},
            {"date": "2026-01-05", "y": 14},
        ]
        measurement = {
            "kind": "rolling_origin_naive_mae",
            "field": "y",
            "minimum_history": 2,
            "horizon": 1,
        }
        result = run_hypothesis_experiment(atomic_spec(measurement, rows, {"operator": "lte", "value": 2}))
        measured = result["dimensions"]["path"]["components"][0]["measurement"]
        self.assertEqual(measured["value"], 2.0)
        self.assertEqual(measured["prediction_count"], 3)
        self.assertEqual(measured["predictions"][0]["origin_time"], "2026-01-02")
        self.assertEqual(measured["predictions"][0]["target_time"], "2026-01-03")
        self.assertEqual(measured["horizon_unit"], "usable_observations")

    def test_prediction_result_binding_is_echoed_and_must_match_measurement(self) -> None:
        rows = [
            {"date": "2026-01-01", "y": 10}, {"date": "2026-01-02", "y": 12},
            {"date": "2026-01-03", "y": 11}, {"date": "2026-01-04", "y": 15},
        ]
        measurement = {"kind": "rolling_origin_naive_mae", "field": "y", "minimum_history": 2, "horizon": 1}
        spec = atomic_spec(measurement, rows, {"operator": "lte", "value": 4})
        spec["data_source"] = {
            "path": "prediction-series.json", "format": "json",
            "granularity": "daily", "time_field": "date",
        }
        spec["data_evidence_refs"] = ["EV-PREDICTION-DATA-1"]
        spec["analysis_binding"] = {
            "analysis_layer": "predictive", "target": "next observed y",
            "validation_type": "out_of_sample", "method": "rolling_origin_naive_mae",
            "component_id": "PROBE-1", "design_evidence_refs": ["EV-SPLIT-1"],
            "outcome_field": "y",
            "validation_design": "rolling_origin", "horizon": "1 usable_observations",
            "horizon_steps": 1, "horizon_unit": "usable_observations",
            "cutoff": "each rolling origin", "cutoff_mode": "rolling_origin",
            "metric": "MAE", "baseline_model": "last_observation",
            "baseline_kind": "last_observation",
        }
        result = run_hypothesis_experiment(spec, FIXTURE)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["analysis_binding"], spec["analysis_binding"])

        mismatched = deepcopy(spec)
        mismatched["analysis_binding"]["method"] = "group_mean_difference"
        rejected = run_hypothesis_experiment(mismatched, FIXTURE)
        self.assertEqual(rejected["execution_status"], "invalid_spec")

        wrong_outcome = deepcopy(spec)
        wrong_outcome["analysis_binding"]["outcome_field"] = "weather"
        rejected = run_hypothesis_experiment(wrong_outcome, FIXTURE)
        self.assertEqual(rejected["execution_status"], "invalid_spec")

        contradictory_labels = deepcopy(spec)
        contradictory_labels["analysis_binding"]["horizon"] = "one calendar month"
        contradictory_labels["analysis_binding"]["cutoff"] = "2024-09-30"
        contradictory_labels["analysis_binding"]["baseline_model"] = "seasonal naive"
        rejected = run_hypothesis_experiment(contradictory_labels, FIXTURE)
        self.assertEqual(rejected["execution_status"], "invalid_spec")

    def test_randomized_binding_rejects_reversed_treatment_groups(self) -> None:
        measurement = {
            "kind": "group_mean_difference", "field": "read_through",
            "group_field": "opening_arm", "group_a": "steps_first",
            "group_b": "result_first",
        }
        spec = atomic_spec(measurement, [], {"operator": "gt", "value": -1})
        spec["data_source"] = {
            "path": "../deep-findings/synthetic-experiment-data.json",
            "format": "json", "granularity": "daily",
        }
        spec["data_evidence_refs"] = ["E-DATA-1"]
        spec["analysis_binding"] = {
            "analysis_layer": "causal", "target": "两种开头的平均继续阅读率差",
            "validation_type": "randomized_experiment",
            "method": "group_mean_difference", "component_id": "PROBE-1",
            "design_evidence_refs": ["E-DESIGN-1"], "outcome_field": "read_through",
            "identification_strategy": "randomized", "intervention": "结果前置开头",
            "comparator": "步骤前置开头", "group_field": "opening_arm",
            "intervention_value": "result_first", "comparator_value": "steps_first",
        }
        result = run_hypothesis_experiment(spec, FIXTURE)
        self.assertEqual(result["execution_status"], "invalid_spec")
        self.assertTrue(any("intervention_value" in error for error in result["errors"]))

    def test_rolling_origin_rejects_multiple_series_at_same_timestamp(self) -> None:
        rows = [
            {"date": "2026-01-01", "series": "a", "y": 10},
            {"date": "2026-01-01", "series": "b", "y": 20},
            {"date": "2026-01-02", "series": "a", "y": 11},
            {"date": "2026-01-03", "series": "a", "y": 12},
        ]
        measurement = {
            "kind": "rolling_origin_naive_mae",
            "field": "y",
            "minimum_history": 2,
            "horizon": 1,
        }
        result = run_hypothesis_experiment(atomic_spec(measurement, rows, {"operator": "lte", "value": 2}))
        component = result["dimensions"]["path"]["components"][0]
        self.assertEqual(component["status"], "unverifiable")
        self.assertIn("unique timestamp", component["reason"])


if __name__ == "__main__":
    unittest.main()
