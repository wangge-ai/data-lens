from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))

from run_deep_analysis_execution import run_deep_analysis_execution


class DeepAnalysisExecutionTests(unittest.TestCase):
    def _run(
        self,
        rows: list[dict],
        binding: dict,
        *,
        time_field: str = "date",
        contract_version: str = "data-lens-deep-analysis-execution/0.1",
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data.json"
            data.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            source = {"path": data.name, "format": "json", "granularity": "daily"}
            if time_field:
                source["time_field"] = time_field
            spec = {
                "contract_version": contract_version,
                "execution_id": binding["component_id"],
                "decision_question": "哪种解释、预测或行动更值得采用？",
                "analysis_binding": binding,
                "data_source": source,
                "data_evidence_refs": ["E-DATA"],
            }
            return run_deep_analysis_execution(spec, root)

    @staticmethod
    def _prediction_binding(component_id: str) -> dict:
        return {
            "analysis_layer": "predictive", "target": "下一条 y",
            "validation_type": "out_of_sample",
            "method": "rolling_origin_model_competition", "component_id": component_id,
            "analysis_unit": "day", "outcome_field": "y", "time_field": "date",
            "validation_design": "rolling_origin", "horizon": "1 usable_observations",
            "horizon_steps": 1, "cutoff": "each rolling origin", "cutoff_mode": "rolling_origin",
            "horizon_unit": "usable_observations", "metric": "mae", "minimum_history": 4,
            "minimum_improvement": 0.05, "baseline_model": "last_observation",
            "baseline_kind": "last_observation", "baseline_model_id": "last",
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
            ],
            "uncertainty_method": "circular_block_bootstrap",
            "confidence_level": 0.95, "bootstrap_replicates": 300,
            "bootstrap_seed": 17, "block_length": 2, "minimum_origins": 8,
        }

    @staticmethod
    def _offline_binding(component_id: str, *, estimators: list[str] | None = None) -> dict:
        estimator_list = estimators or ["ips", "snips"]
        policies = [
            {
                "policy_id": "always_a",
                "policy_type": "explicit_probabilities",
                "action_probability_fields": {"A": "pa_a", "B": "pa_b"},
            },
            {
                "policy_id": "always_b",
                "policy_type": "explicit_probabilities",
                "action_probability_fields": {"A": "pb_a", "B": "pb_b"},
            },
        ]
        if "doubly_robust" in estimator_list:
            policies[0]["q_policy_field"] = "q_a"
            policies[1]["q_policy_field"] = "q_b"
        result = {
            "analysis_layer": "decision", "target": "选择离线策略",
            "validation_type": "policy_evaluation",
            "method": "offline_policy_value_sensitivity", "component_id": component_id,
            "analysis_unit": "logged decision", "outcome_field": "reward",
            "evidence_basis": "causal_effect", "actor": "owner",
            "evaluation_mode": "logged_policy", "logged_action_field": "action",
            "bootstrap_unit_field": "unit",
            "action_values": ["A", "B"],
            "action_options": ["always_a", "always_b"],
            "reward_field": "reward", "propensity_field": "propensity",
            "baseline_action": "always_a", "fallback_action": "always_a",
            "utility_metric": "mean reward", "decision_threshold": "lower interval clears 0.5",
            "minimum_advantage": 0.5, "estimators": estimator_list,
            "primary_estimator": estimator_list[0], "policy_specs": policies,
            "minimum_effective_sample_size": 20, "maximum_importance_weight": 5,
            "confidence_level": 0.95, "bootstrap_replicates": 300,
            "bootstrap_seed": 23, "weight_clip_grid": [2, 4],
            "propensity_floor_grid": [0.01, 0.1],
            "withdrawal_condition": "logged overlap or reward definition changes",
        }
        if "doubly_robust" in estimator_list:
            result["q_logged_field"] = "q_logged"
        return result

    def test_heterogeneity_reports_supported_and_insufficient_subgroups(self) -> None:
        rows = []
        for segment, a_values, b_values in (
            ("new", [9, 10], [5, 6]),
            ("returning", [4, 5], [8, 9]),
            ("tiny", [7], [6]),
        ):
            for value in a_values:
                rows.append({"segment": segment, "arm": "A", "y": value})
            for value in b_values:
                rows.append({"segment": segment, "arm": "B", "y": value})
        binding = {
            "analysis_layer": "heterogeneity",
            "target": "不同客群中的 A-B 差异",
            "validation_type": "subgroup_analysis",
            "method": "subgroup_mean_difference_spread",
            "component_id": "HET-1",
            "analysis_unit": "customer",
            "outcome_field": "y",
            "segment_field": "segment",
            "group_field": "arm",
            "group_a": "A",
            "group_b": "B",
            "minimum_group_n": 2,
            "effect_scope": "descriptive",
        }
        result = self._run(rows, binding, time_field="")
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["coverage_status"], "completed")
        self.assertTrue(result["result"]["primary_value"]["opposite_directions"])
        self.assertEqual(result["result"]["primary_value"]["eligible_subgroup_count"], 2)
        tiny = next(item for item in result["result"]["subgroups"] if item["subgroup"] == "tiny")
        self.assertEqual(tiny["support_status"], "insufficient")

    def test_heterogeneity_needs_two_supported_subgroups(self) -> None:
        rows = [
            {"segment": "one", "arm": "A", "y": 3},
            {"segment": "one", "arm": "A", "y": 4},
            {"segment": "one", "arm": "B", "y": 1},
            {"segment": "one", "arm": "B", "y": 2},
        ]
        binding = {
            "analysis_layer": "heterogeneity", "target": "分群差异",
            "validation_type": "subgroup_analysis", "method": "subgroup_mean_difference_spread",
            "component_id": "HET-2", "analysis_unit": "customer", "outcome_field": "y",
            "segment_field": "segment", "group_field": "arm", "group_a": "A", "group_b": "B",
            "minimum_group_n": 2, "effect_scope": "descriptive",
        }
        result = self._run(rows, binding, time_field="")
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["coverage_status"], "inconclusive")

    def test_honest_heterogeneity_separates_discovery_from_estimation(self) -> None:
        rows = []
        unit = 0
        values = {
            "discover": {"s1": ([10, 11, 12], [1, 2, 3]), "s2": ([1, 2, 3], [10, 11, 12])},
            "estimate": {"s1": ([20, 21, 22], [1, 2, 3]), "s2": ([9, 10, 11], [1, 2, 3])},
        }
        for split, segments in values.items():
            for segment, (a_values, b_values) in segments.items():
                for arm, arm_values in (("A", a_values), ("B", b_values)):
                    for value in arm_values:
                        unit += 1
                        rows.append({
                            "unit": f"u{unit}", "split": split, "segment": segment,
                            "arm": arm, "y": value,
                        })
        binding = {
            "analysis_layer": "heterogeneity", "target": "诚实分样本分群差异",
            "validation_type": "subgroup_analysis", "method": "honest_subgroup_mean_difference",
            "component_id": "HET-HONEST", "analysis_unit": "customer", "outcome_field": "y",
            "segment_field": "segment", "group_field": "arm", "group_a": "A", "group_b": "B",
            "effect_scope": "descriptive", "validation_mode": "honest_split",
            "split_field": "split", "discovery_value": "discover", "estimation_value": "estimate",
            "unit_id_field": "unit", "discovery_min_group_n": 3,
            "estimation_min_group_n": 3, "discovery_min_abs_difference": 5,
            "max_selected_subgroups": 2, "minimum_confirmed_subgroups": 2,
            "selection_metric": "absolute_difference",
            "confirmation_rule": "same_direction_and_interval_excludes_zero",
        }
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["coverage_status"], "completed")
        self.assertEqual(result["result"]["split_audit"]["overlapping_unit_count"], 0)
        self.assertEqual(result["result"]["primary_value"]["confirmed_subgroup_count"], 1)
        self.assertEqual(
            result["result"]["primary_value"]["heterogeneity_confirmation"],
            "not_confirmed",
        )

    def test_honest_heterogeneity_rejects_unit_leakage_between_splits(self) -> None:
        rows = [
            {"unit": "same", "split": split, "segment": "s1", "arm": arm, "y": value}
            for split, arm, value in (
                ("discover", "A", 3), ("discover", "B", 1),
                ("estimate", "A", 4), ("estimate", "B", 2),
            )
        ]
        binding = {
            "analysis_layer": "heterogeneity", "target": "诚实分样本分群差异",
            "validation_type": "subgroup_analysis", "method": "honest_subgroup_mean_difference",
            "component_id": "HET-LEAK", "analysis_unit": "customer", "outcome_field": "y",
            "segment_field": "segment", "group_field": "arm", "group_a": "A", "group_b": "B",
            "effect_scope": "descriptive", "validation_mode": "honest_split",
            "split_field": "split", "discovery_value": "discover", "estimation_value": "estimate",
            "unit_id_field": "unit", "discovery_min_group_n": 2,
            "estimation_min_group_n": 2, "discovery_min_abs_difference": 0,
            "max_selected_subgroups": 2, "minimum_confirmed_subgroups": 2,
            "selection_metric": "absolute_difference",
            "confirmation_rule": "same_direction_and_interval_excludes_zero",
        }
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["execution_status"], "unverifiable")
        self.assertIn("contaminated", result["errors"][0])

    def test_direct_mechanism_test_selects_one_frozen_hypothesis(self) -> None:
        rows = [
            {"date": "2026-01-01", "mediator": 1},
            {"date": "2026-01-02", "mediator": 3},
            {"date": "2026-01-03", "mediator": 5},
        ]
        binding = {
            "analysis_layer": "mechanism", "target": "提醒是否通过提高中介变量起作用",
            "validation_type": "direct_mechanism_test", "method": "mean",
            "component_id": "MECH-1", "analysis_unit": "day", "outcome_field": "mediator",
            "mechanism_id": "M1", "mechanism_variable": "reminder_intensity",
            "changed_or_isolated_variable": "reminder_intensity",
            "baseline_hypothesis_id": "E0", "candidate_hypothesis_id": "E1",
            "required_granularity": "daily",
            "evaluation_window": {"start": "2026-01-01", "end": "2026-01-03"},
            "measurement": {"kind": "mean", "field": "mediator"},
            "hypothesis_predictions": {
                "E0": {"operator": "lt", "value": 2},
                "E1": {"operator": "gte", "value": 2},
            },
        }
        result = self._run(rows, binding)
        self.assertEqual(result["coverage_status"], "completed")
        self.assertEqual(result["result"]["primary_value"]["evidence_direction"], "supports_candidate")
        self.assertTrue(result["result"]["discriminated"])

    def test_mechanism_test_rejects_a_different_changed_variable(self) -> None:
        binding = {
            "analysis_layer": "mechanism", "target": "机制", "validation_type": "direct_mechanism_test",
            "method": "mean", "component_id": "MECH-2", "analysis_unit": "day", "outcome_field": "y",
            "mechanism_id": "M1", "mechanism_variable": "price", "changed_or_isolated_variable": "ad_spend",
            "baseline_hypothesis_id": "E0", "candidate_hypothesis_id": "E1", "required_granularity": "daily",
            "evaluation_window": {"start": "2026-01-01", "end": "2026-01-02"},
            "measurement": {"kind": "mean", "field": "y"},
            "hypothesis_predictions": {"E0": {"operator": "lt", "value": 0}, "E1": {"operator": "gte", "value": 0}},
        }
        result = self._run([{"date": "2026-01-01", "y": 1}], binding)
        self.assertEqual(result["execution_status"], "invalid_spec")
        self.assertIn(
            "mechanism direct test must change or isolate the declared mechanism variable",
            result["errors"],
        )

    def test_prediction_compares_models_on_identical_rolling_origins(self) -> None:
        rows = [
            {"date": f"2026-01-{day:02d}", "y": 2 * day + 1}
            for day in range(1, 11)
        ]
        binding = {
            "analysis_layer": "predictive", "target": "下一条 y", "validation_type": "out_of_sample",
            "method": "rolling_origin_model_competition", "component_id": "PRED-1",
            "analysis_unit": "day", "outcome_field": "y", "time_field": "date",
            "validation_design": "rolling_origin", "horizon": "1 usable_observations",
            "horizon_steps": 1, "cutoff": "each rolling origin", "cutoff_mode": "rolling_origin",
            "horizon_unit": "usable_observations", "metric": "mae", "minimum_history": 3,
            "minimum_improvement": 0.05, "baseline_model": "last_observation",
            "baseline_kind": "last_observation", "baseline_model_id": "last",
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
                {"model_id": "mean3", "kind": "rolling_mean", "window": 3},
            ],
        }
        result = self._run(rows, binding)
        self.assertEqual(result["coverage_status"], "completed")
        primary = result["result"]["primary_value"]
        self.assertEqual(primary["selected_model_id"], "trend")
        self.assertEqual(primary["comparison_result"], "candidate_wins")
        self.assertGreater(primary["relative_improvement"], 0.9)
        self.assertTrue(all(
            record["origin_time"] < record["target_time"]
            for record in result["result"]["predictions"]
        ))

    def test_prediction_rejects_duplicate_timestamps(self) -> None:
        rows = [
            {"date": f"2026-01-{day:02d}", "y": day}
            for day in range(1, 7)
        ] + [{"date": "2026-01-06", "y": 99}]
        binding = {
            "analysis_layer": "predictive", "target": "下一条 y", "validation_type": "out_of_sample",
            "method": "rolling_origin_model_competition", "component_id": "PRED-2",
            "analysis_unit": "day", "outcome_field": "y", "time_field": "date",
            "validation_design": "rolling_origin", "horizon": "1 usable_observations",
            "horizon_steps": 1, "cutoff": "each rolling origin", "cutoff_mode": "rolling_origin",
            "horizon_unit": "usable_observations", "metric": "mae", "minimum_history": 2,
            "minimum_improvement": 0.0, "baseline_model": "last_observation",
            "baseline_kind": "last_observation", "baseline_model_id": "last",
            "model_specs": [
                {"model_id": "last", "kind": "last_observation"},
                {"model_id": "trend", "kind": "linear_trend"},
            ],
        }
        result = self._run(rows, binding)
        self.assertEqual(result["execution_status"], "unverifiable")
        self.assertIn("unique timestamp", result["errors"][0])

    def test_prediction_requires_interval_before_candidate_can_win(self) -> None:
        rows = [
            {"date": f"2026-01-{day:02d}", "y": 3 * day + 2}
            for day in range(1, 25)
        ]
        binding = self._prediction_binding("PRED-UNCERTAINTY")
        first = self._run(
            rows, binding, contract_version="data-lens-deep-analysis-execution/0.2"
        )
        second = self._run(
            rows, binding, contract_version="data-lens-deep-analysis-execution/0.2"
        )
        self.assertEqual(first, second)
        self.assertEqual(first["result"]["primary_value"]["comparison_result"], "candidate_wins")
        interval = first["result"]["paired_loss_comparisons"][0]["mean_loss_difference_interval"]
        self.assertGreater(interval[0], 0)

    def test_prediction_adjusts_intervals_for_multiple_competitors(self) -> None:
        rows = [
            {"date": f"2026-03-{day:02d}", "y": 2 * day}
            for day in range(1, 25)
        ]
        binding = self._prediction_binding("PRED-MULTIPLE")
        binding["model_specs"].append(
            {"model_id": "mean3", "kind": "rolling_mean", "window": 3}
        )
        result = self._run(
            rows, binding, contract_version="data-lens-deep-analysis-execution/0.2"
        )
        self.assertEqual(len(result["result"]["paired_loss_comparisons"]), 2)
        self.assertEqual(
            result["result"]["uncertainty"]["per_comparison_confidence_level"],
            0.975,
        )

    def test_prediction_keeps_baseline_when_loss_interval_crosses_zero(self) -> None:
        values = [
            0.941715, -1.396578, -0.679714, 0.370504, -1.016349,
            -0.07212, 0.179196, -0.831099, -1.309037, 0.193888,
            0.99325, -0.646982, -0.333668, 1.645672, -0.55889,
            -0.514157, 2.404119, -1.531083, 0.796466, -2.003649,
            -0.596963, 1.503681, 1.221436, -0.90112, -0.453699,
        ]
        rows = [
            {"date": f"2026-02-{day:02d}", "y": value}
            for day, value in enumerate(values, start=1)
        ]
        binding = self._prediction_binding("PRED-UNCERTAIN")
        binding["minimum_improvement"] = 0
        binding["model_specs"][1] = {
            "model_id": "trend", "kind": "rolling_mean", "window": 3,
        }
        result = self._run(
            rows, binding, contract_version="data-lens-deep-analysis-execution/0.2"
        )
        primary = result["result"]["primary_value"]
        interval = result["result"]["paired_loss_comparisons"][0]["mean_loss_difference_interval"]
        self.assertGreater(primary["relative_improvement"], 0)
        self.assertLessEqual(interval[0], 0)
        self.assertEqual(primary["comparison_result"], "uncertain_difference")
        self.assertEqual(primary["selected_model_id"], "last")

    def test_decision_selects_highest_feasible_utility_above_threshold(self) -> None:
        rows = [
            {"action": "keep", "benefit": 8, "cost": 2, "probability": 1, "budget": 2},
            {"action": "pilot", "benefit": 20, "cost": 5, "probability": 0.8, "budget": 5},
            {"action": "scale", "benefit": 40, "cost": 20, "probability": 0.8, "budget": 20},
        ]
        binding = {
            "analysis_layer": "decision", "target": "选择推广动作", "validation_type": "policy_evaluation",
            "method": "expected_net_utility", "component_id": "DEC-1", "analysis_unit": "scenario",
            "outcome_field": "benefit", "evidence_basis": "causal_effect", "actor": "owner",
            "action_field": "action",
            "action_options": ["keep", "pilot", "scale"], "benefit_field": "benefit", "cost_field": "cost",
            "probability_field": "probability", "baseline_action": "keep", "fallback_action": "keep",
            "utility_metric": "expected benefit minus cost", "minimum_net_utility": 8,
            "decision_threshold": "net utility and advantage clear thresholds",
            "minimum_advantage": 2, "constraint_rules": [
                {"field": "budget", "aggregation": "max", "operator": "lte", "value": 10}
            ],
            "withdrawal_condition": "observed net utility falls below zero",
        }
        result = self._run(rows, binding, time_field="")
        self.assertEqual(result["coverage_status"], "completed")
        self.assertEqual(result["result"]["primary_value"]["selected_action"], "pilot")
        scale = next(item for item in result["result"]["actions"] if item["action"] == "scale")
        self.assertFalse(scale["feasible"])

    def test_decision_uses_fallback_when_gain_does_not_clear_threshold(self) -> None:
        rows = [
            {"action": "keep", "benefit": 8, "cost": 2},
            {"action": "pilot", "benefit": 9, "cost": 2},
        ]
        binding = {
            "analysis_layer": "decision", "target": "选择动作", "validation_type": "policy_evaluation",
            "method": "expected_net_utility", "component_id": "DEC-2", "analysis_unit": "scenario",
            "outcome_field": "benefit", "evidence_basis": "prediction", "actor": "owner",
            "action_field": "action",
            "action_options": ["keep", "pilot"], "benefit_field": "benefit", "cost_field": "cost",
            "baseline_action": "keep", "fallback_action": "keep", "utility_metric": "net utility",
            "decision_threshold": "net utility and advantage clear thresholds",
            "minimum_net_utility": 0, "minimum_advantage": 2, "constraint_rules": [],
            "withdrawal_condition": "utility below zero",
        }
        result = self._run(rows, binding, time_field="")
        self.assertEqual(result["result"]["primary_value"]["selected_action"], "keep")
        self.assertEqual(result["result"]["primary_value"]["decision_status"], "fallback_selected")

    def test_offline_policy_evaluation_selects_supported_policy(self) -> None:
        rows = []
        for index in range(100):
            action = "A" if index % 2 == 0 else "B"
            rows.append({
                "unit": f"u{index}",
                "action": action, "reward": 1 if action == "A" else 3,
                "propensity": 0.5, "pa_a": 1, "pa_b": 0,
                "pb_a": 0, "pb_b": 1,
            })
        binding = self._offline_binding("DEC-OPE")
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["coverage_status"], "completed")
        self.assertEqual(result["result"]["primary_value"]["selected_policy_id"], "always_b")
        self.assertGreater(result["result"]["primary_value"]["advantage_interval"][0], 0.5)
        self.assertTrue(result["result"]["sensitivity_stable"])

    def test_offline_policy_supports_logging_and_uniform_policy_types(self) -> None:
        rows = [
            {
                "unit": f"u{index}", "action": "A" if index < 80 else "B",
                "reward": 1 if index < 80 else 3,
                "propensity": 0.8 if index < 80 else 0.2,
            }
            for index in range(100)
        ]
        binding = self._offline_binding("DEC-POLICY-TYPES")
        binding.update({
            "minimum_advantage": 0.1,
            "maximum_importance_weight": 3,
            "policy_specs": [
                {"policy_id": "always_a", "policy_type": "logging_policy"},
                {"policy_id": "always_b", "policy_type": "uniform_policy"},
            ],
        })
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["coverage_status"], "completed")
        self.assertEqual(result["result"]["primary_value"]["selected_policy_id"], "always_b")

    def test_offline_policy_evaluation_refuses_low_overlap(self) -> None:
        rows = []
        for index in range(100):
            action = "B" if index == 0 else "A"
            propensity = 0.01 if action == "B" else 0.99
            rows.append({
                "unit": f"u{index}",
                "action": action, "reward": 10 if action == "B" else 1,
                "propensity": propensity, "pa_a": 1, "pa_b": 0,
                "pb_a": 0, "pb_b": 1,
            })
        binding = self._offline_binding("DEC-OVERLAP", estimators=["ips"])
        binding["minimum_effective_sample_size"] = 0.5
        binding["maximum_importance_weight"] = 10
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["result"]["primary_value"]["selected_policy_id"], "always_a")
        self.assertIn(
            "overlap_diagnostic_failed",
            result["result"]["primary_value"]["failure_reasons"],
        )

    def test_offline_policy_overlap_uses_independent_units_not_row_count(self) -> None:
        rows = []
        for unit in range(4):
            for repeat in range(20):
                action = "A" if (unit + repeat) % 2 == 0 else "B"
                rows.append({
                    "unit": f"customer-{unit}", "action": action,
                    "reward": 1 if action == "A" else 3, "propensity": 0.5,
                    "pa_a": 1, "pa_b": 0, "pb_a": 0, "pb_b": 1,
                })
        binding = self._offline_binding("DEC-CLUSTER", estimators=["ips"])
        binding["minimum_effective_sample_size"] = 10
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        candidate = next(
            item for item in result["result"]["policies"]
            if item["policy_id"] == "always_b"
        )
        self.assertEqual(candidate["independent_unit_count"], 4)
        self.assertLessEqual(candidate["effective_sample_size"], 4)
        self.assertEqual(candidate["overlap_status"], "failed")

    def test_offline_policy_sensitivity_can_reverse_the_recommendation(self) -> None:
        rows = []
        for index in range(10):
            action = "B" if index == 0 else "A"
            rows.append({
                "unit": f"u{index}",
                "action": action, "reward": 10 if action == "B" else 2,
                "propensity": 0.1 if action == "B" else 0.9,
                "pa_a": 1, "pa_b": 0, "pb_a": 0, "pb_b": 1,
            })
        binding = self._offline_binding("DEC-SENSITIVE", estimators=["ips"])
        binding.update({
            "minimum_effective_sample_size": 0.5,
            "maximum_importance_weight": 20,
            "minimum_advantage": 0.1,
            "weight_clip_grid": [1],
            "propensity_floor_grid": [0.01],
        })
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["result"]["primary_value"]["selected_policy_id"], "always_a")
        self.assertIn(
            "sensitivity_result_unstable",
            result["result"]["primary_value"]["failure_reasons"],
        )

    def test_offline_policy_requires_estimator_agreement(self) -> None:
        rows = []
        for unit in range(30):
            rows.extend([
                {
                    "unit": f"u{unit}", "action": "A", "reward": 5,
                    "propensity": 0.9, "pa_a": 1, "pa_b": 0,
                    "pb_a": 0, "pb_b": 1,
                },
                {
                    "unit": f"u{unit}", "action": "B", "reward": 2,
                    "propensity": 0.1, "pa_a": 1, "pa_b": 0,
                    "pb_a": 0, "pb_b": 1,
                },
            ])
        binding = self._offline_binding("DEC-ESTIMATORS")
        binding.update({
            "minimum_effective_sample_size": 20,
            "maximum_importance_weight": 20,
            "minimum_advantage": 0.1,
            "primary_estimator": "ips",
            "weight_clip_grid": [20],
            "propensity_floor_grid": [0.01],
        })
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        self.assertEqual(result["result"]["primary_value"]["selected_policy_id"], "always_a")
        self.assertFalse(result["result"]["estimator_agreement"])
        self.assertIn(
            "estimator_disagreement",
            result["result"]["primary_value"]["failure_reasons"],
        )

    def test_doubly_robust_policy_value_uses_bound_outcome_models(self) -> None:
        rows = []
        for index in range(40):
            action = "A" if index % 2 == 0 else "B"
            rows.append({
                "unit": f"u{index}",
                "action": action, "reward": 1 if action == "A" else 3,
                "propensity": 0.5, "pa_a": 1, "pa_b": 0,
                "pb_a": 0, "pb_b": 1, "q_logged": 1 if action == "A" else 3,
                "q_a": 1, "q_b": 3,
            })
        binding = self._offline_binding("DEC-DR", estimators=["doubly_robust"])
        binding["primary_estimator"] = "doubly_robust"
        result = self._run(
            rows, binding, time_field="",
            contract_version="data-lens-deep-analysis-execution/0.2",
        )
        values = {
            item["policy_id"]: item["estimated_values"]["doubly_robust"]
            for item in result["result"]["policies"]
        }
        self.assertEqual(values, {"always_a": 1.0, "always_b": 3.0})

    def test_bound_execution_rejects_inline_rows(self) -> None:
        binding = {
            "analysis_layer": "heterogeneity", "target": "分群差异",
            "validation_type": "subgroup_analysis", "method": "subgroup_mean_difference_spread",
            "component_id": "HET-INLINE", "analysis_unit": "row", "outcome_field": "y",
            "segment_field": "segment", "group_field": "group", "group_a": "A", "group_b": "B",
            "minimum_group_n": 2, "effect_scope": "descriptive",
        }
        spec = {
            "contract_version": "data-lens-deep-analysis-execution/0.1",
            "execution_id": "HET-INLINE", "decision_question": "问题", "analysis_binding": binding,
            "data_source": {"rows": [], "granularity": "daily"}, "data_evidence_refs": ["E-DATA"],
        }
        result = run_deep_analysis_execution(spec)
        self.assertEqual(result["execution_status"], "invalid_spec")
        self.assertIn("deep analysis execution requires a file data_source", result["errors"])

    def test_cli_cannot_overwrite_the_bound_data_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data.json"
            data.write_text(json.dumps([
                {"segment": "one", "group": "A", "y": 2},
                {"segment": "one", "group": "A", "y": 3},
                {"segment": "one", "group": "B", "y": 1},
                {"segment": "one", "group": "B", "y": 1.5},
            ]), encoding="utf-8")
            before = data.read_bytes()
            binding = {
                "analysis_layer": "heterogeneity", "target": "分群差异",
                "validation_type": "subgroup_analysis",
                "method": "subgroup_mean_difference_spread",
                "component_id": "HET-PROTECT", "analysis_unit": "row",
                "outcome_field": "y", "segment_field": "segment",
                "group_field": "group", "group_a": "A", "group_b": "B",
                "minimum_group_n": 2, "effect_scope": "descriptive",
            }
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "contract_version": "data-lens-deep-analysis-execution/0.1",
                "execution_id": "HET-PROTECT", "decision_question": "问题",
                "analysis_binding": binding,
                "data_source": {"path": data.name, "format": "json", "granularity": "daily"},
                "data_evidence_refs": ["E-DATA"],
            }, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "run_deep_analysis_execution.py"),
                 "--spec", str(spec), "--output", str(data)],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(data.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
