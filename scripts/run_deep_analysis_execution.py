from __future__ import annotations

import argparse
import copy
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from run_hypothesis_experiment import (
    ExperimentError,
    GRANULARITY_MINUTES,
    _filter_window,
    _granularity_sufficient,
    _load_rows,
    _measure,
    _normalize,
    _number,
    _ordered,
    _predicate,
    _round,
    _text,
)


LEGACY_SPEC_VERSION = "data-lens-deep-analysis-execution/0.1"
SPEC_VERSION = "data-lens-deep-analysis-execution/0.2"
LEGACY_RESULT_VERSION = "data-lens-deep-analysis-execution-result/0.1"
RESULT_VERSION = "data-lens-deep-analysis-execution-result/0.2"
SUPPORTED_SPEC_VERSIONS = {LEGACY_SPEC_VERSION, SPEC_VERSION}
LAYERS = {"heterogeneity", "mechanism", "predictive", "decision"}
VALIDATION_TYPES = {
    "heterogeneity": {"subgroup_analysis"},
    "mechanism": {"direct_mechanism_test"},
    "predictive": {"out_of_sample"},
    "decision": {"policy_evaluation"},
}
METHODS = {
    "heterogeneity": {
        "subgroup_mean_difference_spread", "honest_subgroup_mean_difference",
    },
    "mechanism": {
        "mean", "median", "proportion", "group_mean_difference",
        "group_median_difference", "group_rate_difference", "lagged_pearson",
    },
    "predictive": {"rolling_origin_model_competition"},
    "decision": {"expected_net_utility", "offline_policy_value_sensitivity"},
}
MODEL_KINDS = {"last_observation", "rolling_mean", "linear_trend", "seasonal_naive"}
METRICS = {"mae", "rmse"}
CONSTRAINT_AGGREGATIONS = {"sum", "mean", "min", "max"}
POLICY_ESTIMATORS = {"ips", "snips", "doubly_robust"}
POLICY_TYPES = {"explicit_probabilities", "logging_policy", "uniform_policy"}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _integer_at_least(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _number_list(
    value: Any,
    field: str,
    errors: list[str],
    *,
    minimum: int = 1,
    lower_exclusive: float | None = None,
    upper_exclusive: float | None = None,
) -> list[float]:
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    result: list[float] = []
    for item in value:
        if not _finite_number(item):
            errors.append(f"{field} must contain only finite numbers")
            return []
        number = float(item)
        if lower_exclusive is not None and number <= lower_exclusive:
            errors.append(f"{field} values must be > {lower_exclusive}")
            return []
        if upper_exclusive is not None and number >= upper_exclusive:
            errors.append(f"{field} values must be < {upper_exclusive}")
            return []
        result.append(number)
    if len(result) < minimum or len(result) != len(set(result)):
        errors.append(f"{field} must contain at least {minimum} unique values")
    return result


def _text_list(value: Any, field: str, errors: list[str], *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value) or len(result) < minimum or len(result) != len(set(result)):
        errors.append(f"{field} must contain at least {minimum} unique non-empty strings")
    return result


def _binding_errors(binding: Any, contract_version: str) -> list[str]:
    if not isinstance(binding, dict):
        return ["analysis_binding must be an object"]
    errors: list[str] = []
    for field in (
        "analysis_layer", "target", "validation_type", "method", "component_id",
        "analysis_unit", "outcome_field",
    ):
        if not _text(binding.get(field)):
            errors.append(f"analysis_binding.{field} is required")
    layer = _text(binding.get("analysis_layer"))
    validation = _text(binding.get("validation_type"))
    method = _text(binding.get("method"))
    if layer not in LAYERS:
        errors.append("analysis_binding.analysis_layer is invalid")
        return errors
    if validation not in VALIDATION_TYPES[layer]:
        errors.append("analysis_binding.validation_type is incompatible with analysis_layer")
    if method not in METHODS[layer]:
        errors.append("analysis_binding.method is incompatible with analysis_layer")

    if layer == "heterogeneity":
        for field in ("segment_field", "group_field"):
            if not _text(binding.get(field)):
                errors.append(f"analysis_binding.{field} is required")
        if binding.get("group_a") in (None, "") or binding.get("group_b") in (None, ""):
            errors.append("heterogeneity binding requires group_a and group_b")
        elif binding.get("group_a") == binding.get("group_b"):
            errors.append("heterogeneity binding requires distinct groups")
        minimum_group_n = binding.get("minimum_group_n")
        if method == "subgroup_mean_difference_spread" and not _integer_at_least(
            minimum_group_n, 2
        ):
            errors.append("analysis_binding.minimum_group_n must be an integer >= 2")
        if binding.get("effect_scope") not in {"descriptive", "causal"}:
            errors.append("analysis_binding.effect_scope must be descriptive or causal")
        design_refs = binding.get("design_evidence_refs") or []
        if not isinstance(design_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in design_refs
        ):
            errors.append("analysis_binding.design_evidence_refs must be a string array")
        if binding.get("effect_scope") == "causal" and (
            not isinstance(design_refs, list)
            or not design_refs
            or not all(isinstance(item, str) and item.strip() for item in design_refs)
        ):
            errors.append("causal heterogeneity requires design_evidence_refs")
        if method == "honest_subgroup_mean_difference":
            if contract_version != SPEC_VERSION:
                errors.append("honest heterogeneity requires deep analysis execution contract 0.2")
            if binding.get("validation_mode") != "honest_split":
                errors.append("honest heterogeneity requires validation_mode=honest_split")
            for field in ("split_field", "unit_id_field"):
                if not _text(binding.get(field)):
                    errors.append(f"analysis_binding.{field} is required")
            if binding.get("discovery_value") in (None, "") or binding.get("estimation_value") in (None, ""):
                errors.append("honest heterogeneity requires discovery_value and estimation_value")
            elif binding.get("discovery_value") == binding.get("estimation_value"):
                errors.append("honest heterogeneity requires distinct split values")
            for field in ("discovery_min_group_n", "estimation_min_group_n"):
                if not _integer_at_least(binding.get(field), 2):
                    errors.append(f"analysis_binding.{field} must be an integer >= 2")
            discovery_threshold = binding.get("discovery_min_abs_difference")
            if not _finite_number(discovery_threshold) or (
                _finite_number(discovery_threshold) and float(discovery_threshold) < 0
            ):
                errors.append("analysis_binding.discovery_min_abs_difference must be a finite number >= 0")
            if not _integer_at_least(binding.get("max_selected_subgroups"), 2):
                errors.append("analysis_binding.max_selected_subgroups must be an integer >= 2")
            minimum_confirmed = binding.get("minimum_confirmed_subgroups")
            if not _integer_at_least(minimum_confirmed, 2):
                errors.append("analysis_binding.minimum_confirmed_subgroups must be an integer >= 2")
            elif _integer_at_least(binding.get("max_selected_subgroups"), 2) and minimum_confirmed > binding.get("max_selected_subgroups"):
                errors.append("minimum_confirmed_subgroups cannot exceed max_selected_subgroups")
            if binding.get("selection_metric") != "absolute_difference":
                errors.append("honest heterogeneity requires selection_metric=absolute_difference")
            if binding.get("confirmation_rule") != "same_direction_and_interval_excludes_zero":
                errors.append("honest heterogeneity requires the supported confirmation_rule")
        elif binding.get("validation_mode") not in (None, "", "prespecified"):
            errors.append("prespecified heterogeneity requires validation_mode=prespecified")

    elif layer == "mechanism":
        for field in (
            "mechanism_id", "mechanism_variable", "changed_or_isolated_variable",
            "baseline_hypothesis_id", "candidate_hypothesis_id", "required_granularity",
        ):
            if not _text(binding.get(field)):
                errors.append(f"analysis_binding.{field} is required")
        if _normalize(binding.get("mechanism_variable")) != _normalize(
            binding.get("changed_or_isolated_variable")
        ):
            errors.append("mechanism direct test must change or isolate the declared mechanism variable")
        if binding.get("baseline_hypothesis_id") == binding.get("candidate_hypothesis_id"):
            errors.append("mechanism test requires distinct baseline and candidate hypotheses")
        if not isinstance(binding.get("evaluation_window"), dict):
            errors.append("analysis_binding.evaluation_window must be an object")
        measurement = binding.get("measurement")
        if not isinstance(measurement, dict) or _text(measurement.get("kind")) != method:
            errors.append("analysis_binding.measurement.kind must match method")
        elif _text(measurement.get("field")) != _text(binding.get("outcome_field")):
            errors.append("analysis_binding.measurement.field must match outcome_field")
        predictions = binding.get("hypothesis_predictions")
        expected_ids = {
            _text(binding.get("baseline_hypothesis_id")),
            _text(binding.get("candidate_hypothesis_id")),
        }
        if not isinstance(predictions, dict) or set(predictions) != expected_ids or not all(
            isinstance(item, dict) for item in (predictions or {}).values()
        ):
            errors.append("analysis_binding.hypothesis_predictions must bind exactly the baseline and candidate hypotheses")

    elif layer == "predictive":
        if binding.get("validation_design") != "rolling_origin":
            errors.append("predictive competition currently requires rolling_origin validation")
        for field in (
            "time_field", "horizon", "horizon_unit", "cutoff", "cutoff_mode",
            "baseline_model", "baseline_kind", "baseline_model_id",
        ):
            if not _text(binding.get(field)):
                errors.append(f"analysis_binding.{field} is required")
        horizon = binding.get("horizon_steps")
        minimum_history = binding.get("minimum_history")
        if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
            errors.append("analysis_binding.horizon_steps must be a positive integer")
        else:
            expected_horizon = f"{horizon} {_text(binding.get('horizon_unit'))}"
            if binding.get("horizon") != expected_horizon:
                errors.append("analysis_binding.horizon must be derived from horizon_steps and horizon_unit")
        if binding.get("cutoff_mode") != "rolling_origin" or binding.get("cutoff") != "each rolling origin":
            errors.append("rolling-origin prediction requires the canonical cutoff")
        if binding.get("baseline_model") != binding.get("baseline_kind"):
            errors.append("analysis_binding.baseline_model must be derived from baseline_kind")
        if not isinstance(minimum_history, int) or isinstance(minimum_history, bool) or minimum_history < 2:
            errors.append("analysis_binding.minimum_history must be an integer >= 2")
        if _text(binding.get("metric")).lower() not in METRICS:
            errors.append("analysis_binding.metric must be mae or rmse")
        minimum_improvement = binding.get("minimum_improvement")
        if not isinstance(minimum_improvement, (int, float)) or isinstance(minimum_improvement, bool) or not 0 <= float(minimum_improvement) <= 1:
            errors.append("analysis_binding.minimum_improvement must be between 0 and 1")
        models = binding.get("model_specs")
        if not isinstance(models, list) or len(models) < 2:
            errors.append("analysis_binding.model_specs must contain a baseline and at least one competitor")
            models = []
        model_ids: list[str] = []
        for index, model in enumerate(models):
            if not isinstance(model, dict):
                errors.append(f"analysis_binding.model_specs[{index}] must be an object")
                continue
            model_id = _text(model.get("model_id"))
            kind = _text(model.get("kind"))
            if not model_id or model_id in model_ids:
                errors.append("prediction model_id values must be present and unique")
            model_ids.append(model_id)
            if kind not in MODEL_KINDS:
                errors.append(f"unsupported prediction model kind:{kind}")
            if kind == "rolling_mean" and (
                not isinstance(model.get("window"), int)
                or isinstance(model.get("window"), bool)
                or model.get("window") < 2
            ):
                errors.append("rolling_mean requires window >= 2")
            if kind == "seasonal_naive" and (
                not isinstance(model.get("season_length"), int)
                or isinstance(model.get("season_length"), bool)
                or model.get("season_length") < 2
            ):
                errors.append("seasonal_naive requires season_length >= 2")
        if _text(binding.get("baseline_model_id")) not in model_ids:
            errors.append("analysis_binding.baseline_model_id must reference model_specs")
        if contract_version == SPEC_VERSION:
            if binding.get("uncertainty_method") != "circular_block_bootstrap":
                errors.append("prediction requires uncertainty_method=circular_block_bootstrap")
            confidence = binding.get("confidence_level")
            if not _finite_number(confidence) or not 0 < float(confidence or 0) < 1:
                errors.append("analysis_binding.confidence_level must be between 0 and 1")
            if not _integer_at_least(binding.get("bootstrap_replicates"), 200):
                errors.append("analysis_binding.bootstrap_replicates must be an integer >= 200")
            if not isinstance(binding.get("bootstrap_seed"), int) or isinstance(binding.get("bootstrap_seed"), bool):
                errors.append("analysis_binding.bootstrap_seed must be an integer")
            block_length = binding.get("block_length")
            if not _integer_at_least(block_length, 1):
                errors.append("analysis_binding.block_length must be a positive integer")
            elif _integer_at_least(horizon, 1) and block_length < horizon:
                errors.append("analysis_binding.block_length must be >= horizon_steps")
            if not _integer_at_least(binding.get("minimum_origins"), 5):
                errors.append("analysis_binding.minimum_origins must be an integer >= 5")

    elif layer == "decision":
        for field in (
            "evidence_basis", "actor", "baseline_action", "fallback_action",
            "utility_metric", "decision_threshold", "withdrawal_condition",
        ):
            if not _text(binding.get(field)):
                errors.append(f"analysis_binding.{field} is required")
        if binding.get("evidence_basis") not in {"causal_effect", "prediction", "descriptive_rule"}:
            errors.append("analysis_binding.evidence_basis is invalid")
        actions = _text_list(binding.get("action_options"), "analysis_binding.action_options", errors, minimum=2)
        for field in ("baseline_action", "fallback_action"):
            if _text(binding.get(field)) not in actions:
                errors.append(f"analysis_binding.{field} must reference action_options")
        numeric_thresholds = ("minimum_net_utility", "minimum_advantage") \
            if method == "expected_net_utility" else ("minimum_advantage",)
        for field in numeric_thresholds:
            value = binding.get(field)
            if not _finite_number(value):
                errors.append(f"analysis_binding.{field} must be a finite number")
        if method == "expected_net_utility":
            if binding.get("evaluation_mode") not in (None, "", "scenario_utility"):
                errors.append("expected_net_utility requires evaluation_mode=scenario_utility")
            for field in ("action_field", "benefit_field", "cost_field"):
                if not _text(binding.get(field)):
                    errors.append(f"analysis_binding.{field} is required")
            rules = binding.get("constraint_rules")
            if not isinstance(rules, list):
                errors.append("analysis_binding.constraint_rules must be an array")
                rules = []
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    errors.append(f"analysis_binding.constraint_rules[{index}] must be an object")
                    continue
                if not _text(rule.get("field")):
                    errors.append(f"analysis_binding.constraint_rules[{index}].field is required")
                if rule.get("aggregation") not in CONSTRAINT_AGGREGATIONS:
                    errors.append(f"analysis_binding.constraint_rules[{index}].aggregation is invalid")
                try:
                    predicate = {"operator": rule.get("operator"), "value": rule.get("value")}
                    if rule.get("tolerance") is not None:
                        predicate["tolerance"] = rule.get("tolerance")
                    _predicate(0, predicate)
                except (ExperimentError, TypeError, ValueError):
                    errors.append(f"analysis_binding.constraint_rules[{index}] predicate is invalid")
        else:
            if contract_version != SPEC_VERSION:
                errors.append("offline policy evaluation requires deep analysis execution contract 0.2")
            if binding.get("evaluation_mode") != "logged_policy":
                errors.append("offline policy evaluation requires evaluation_mode=logged_policy")
            for field in (
                "logged_action_field", "reward_field", "propensity_field",
                "bootstrap_unit_field",
            ):
                if not _text(binding.get(field)):
                    errors.append(f"analysis_binding.{field} is required")
            if _text(binding.get("reward_field")) != _text(binding.get("outcome_field")):
                errors.append("offline policy reward_field must match outcome_field")
            action_values = _text_list(
                binding.get("action_values"), "analysis_binding.action_values", errors, minimum=2
            )
            estimators = _text_list(
                binding.get("estimators"), "analysis_binding.estimators", errors
            )
            if any(item not in POLICY_ESTIMATORS for item in estimators):
                errors.append("analysis_binding.estimators contains an unsupported estimator")
            if _text(binding.get("primary_estimator")) not in estimators:
                errors.append("analysis_binding.primary_estimator must reference estimators")
            policy_specs = binding.get("policy_specs")
            if not isinstance(policy_specs, list) or len(policy_specs) < 2:
                errors.append("analysis_binding.policy_specs must contain at least two policies")
                policy_specs = []
            policy_ids: list[str] = []
            for index, policy in enumerate(policy_specs):
                if not isinstance(policy, dict):
                    errors.append(f"analysis_binding.policy_specs[{index}] must be an object")
                    continue
                policy_id = _text(policy.get("policy_id"))
                if not policy_id or policy_id in policy_ids:
                    errors.append("offline policy_id values must be present and unique")
                policy_ids.append(policy_id)
                policy_type = _text(policy.get("policy_type"))
                if policy_type not in POLICY_TYPES:
                    errors.append(f"analysis_binding.policy_specs[{index}].policy_type is invalid")
                fields = policy.get("action_probability_fields")
                if policy_type == "explicit_probabilities" and (
                    not isinstance(fields, dict)
                    or set(fields) != set(action_values)
                    or not all(_text(value) for value in (fields or {}).values())
                ):
                    errors.append(
                        f"analysis_binding.policy_specs[{index}].action_probability_fields must bind every action value"
                    )
                if policy_type != "explicit_probabilities" and fields not in (None, {}):
                    errors.append(
                        f"analysis_binding.policy_specs[{index}].action_probability_fields is only valid for explicit_probabilities"
                    )
                if "doubly_robust" in estimators and not _text(policy.get("q_policy_field")):
                    errors.append(
                        f"analysis_binding.policy_specs[{index}].q_policy_field is required for doubly_robust"
                    )
            if set(policy_ids) != set(actions):
                errors.append("analysis_binding.action_options must equal the offline policy_ids")
            if "doubly_robust" in estimators and not _text(binding.get("q_logged_field")):
                errors.append("analysis_binding.q_logged_field is required for doubly_robust")
            if not _finite_number(binding.get("minimum_effective_sample_size")) or float(
                binding.get("minimum_effective_sample_size") or 0
            ) <= 0:
                errors.append("analysis_binding.minimum_effective_sample_size must be > 0")
            if not _finite_number(binding.get("maximum_importance_weight")) or float(
                binding.get("maximum_importance_weight") or 0
            ) <= 0:
                errors.append("analysis_binding.maximum_importance_weight must be > 0")
            confidence = binding.get("confidence_level")
            if not _finite_number(confidence) or not 0 < float(confidence or 0) < 1:
                errors.append("analysis_binding.confidence_level must be between 0 and 1")
            if not _integer_at_least(binding.get("bootstrap_replicates"), 200):
                errors.append("analysis_binding.bootstrap_replicates must be an integer >= 200")
            if not isinstance(binding.get("bootstrap_seed"), int) or isinstance(binding.get("bootstrap_seed"), bool):
                errors.append("analysis_binding.bootstrap_seed must be an integer")
            _number_list(
                binding.get("weight_clip_grid"), "analysis_binding.weight_clip_grid", errors,
                lower_exclusive=0,
            )
            _number_list(
                binding.get("propensity_floor_grid"), "analysis_binding.propensity_floor_grid", errors,
                lower_exclusive=0, upper_exclusive=1,
            )
    return errors


def _validate_spec(spec: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if not isinstance(spec, dict):
        raise ExperimentError("deep analysis execution specification must be an object")
    errors: list[str] = []
    contract_version = _text(spec.get("contract_version"))
    if contract_version not in SUPPORTED_SPEC_VERSIONS:
        errors.append("unsupported deep analysis execution contract")
    for field in ("execution_id", "decision_question"):
        if not _text(spec.get(field)):
            errors.append(f"{field} is required")
    source = spec.get("data_source")
    if not isinstance(source, dict):
        errors.append("data_source must be an object")
        source = {}
    if not _text(source.get("path")) or source.get("rows") is not None:
        errors.append("deep analysis execution requires a file data_source")
    if _text(source.get("granularity")) not in GRANULARITY_MINUTES:
        errors.append("data_source.granularity is invalid")
    refs = spec.get("data_evidence_refs")
    if not isinstance(refs, list) or not refs or not all(
        isinstance(item, str) and item.strip() for item in refs
    ):
        errors.append("data_evidence_refs must be a non-empty string array")
    binding = spec.get("analysis_binding")
    errors.extend(_binding_errors(binding, contract_version))
    if isinstance(binding, dict) and _text(binding.get("component_id")) != _text(spec.get("execution_id")):
        errors.append("analysis_binding.component_id must equal execution_id")
    return source, binding if isinstance(binding, dict) else {}, errors


def _selected_rows(
    rows: list[dict[str, Any]], source: dict[str, Any], binding: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    window = binding.get("evaluation_window")
    if window is None:
        return rows, None
    return _filter_window(rows, _text(source.get("time_field")), window)


def _run_heterogeneity(
    rows: list[dict[str, Any]], source: dict[str, Any], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    try:
        selected, window = _selected_rows(rows, source, binding)
        outcome = _text(binding.get("outcome_field"))
        segment_field = _text(binding.get("segment_field"))
        group_field = _text(binding.get("group_field"))
        group_a = binding.get("group_a")
        group_b = binding.get("group_b")
        minimum_group_n = int(binding.get("minimum_group_n"))
        observed_segments = sorted(
            {row.get(segment_field) for row in selected if row.get(segment_field) not in (None, "")},
            key=lambda value: str(value),
        )
        subgroups: list[dict[str, Any]] = []
        for segment in observed_segments:
            values_a: list[float] = []
            values_b: list[float] = []
            for row in selected:
                if row.get(segment_field) != segment or row.get(outcome) in (None, ""):
                    continue
                if row.get(group_field) == group_a:
                    values_a.append(_number(row[outcome]))
                elif row.get(group_field) == group_b:
                    values_b.append(_number(row[outcome]))
            sufficient = len(values_a) >= minimum_group_n and len(values_b) >= minimum_group_n
            item: dict[str, Any] = {
                "subgroup": segment,
                "group_a_n": len(values_a),
                "group_b_n": len(values_b),
                "support_status": "sufficient" if sufficient else "insufficient",
            }
            if sufficient:
                mean_a = statistics.fmean(values_a)
                mean_b = statistics.fmean(values_b)
                difference = mean_a - mean_b
                variance_a = statistics.variance(values_a)
                variance_b = statistics.variance(values_b)
                standard_error = math.sqrt(
                    variance_a / len(values_a) + variance_b / len(values_b)
                )
                item.update({
                    "group_a_mean": _round(mean_a),
                    "group_b_mean": _round(mean_b),
                    "difference": _round(difference),
                    "difference_standard_error": _round(standard_error),
                    "normal_approx_95_interval": [
                        _round(difference - 1.96 * standard_error),
                        _round(difference + 1.96 * standard_error),
                    ],
                })
            subgroups.append(item)
        eligible = [item for item in subgroups if item["support_status"] == "sufficient"]
        differences = [float(item["difference"]) for item in eligible]
        completed = len(eligible) >= 2
        primary = {
            "eligible_subgroup_count": len(eligible),
            "effect_spread": _round(max(differences) - min(differences)) if completed else None,
            "opposite_directions": min(differences) < 0 < max(differences) if completed else None,
        }
        result = {
            "primary_value": primary,
            "evaluation_window": window,
            "subgroups": subgroups,
            "excluded_subgroup_count": len(subgroups) - len(eligible),
            "difference_definition": "within-subgroup group_a mean minus group_b mean",
            "uncertainty_boundary": "Intervals use an unadjusted normal approximation and are descriptive diagnostics, not multiplicity-adjusted confirmatory inference.",
            "claim_boundary": (
                "Descriptive subgroup contrasts are not individualized causal effects."
                if binding.get("effect_scope") == "descriptive"
                else "Causal interpretation is limited to the separately verified identification design."
            ),
        }
        return "completed" if completed else "inconclusive", result, []
    except (ExperimentError, TypeError, ValueError) as exc:
        return "unverifiable", {}, [str(exc)]


def _mean_difference_item(
    rows: list[dict[str, Any]],
    binding: dict[str, Any],
    segment: Any,
    minimum_group_n: int,
) -> dict[str, Any]:
    outcome = _text(binding.get("outcome_field"))
    segment_field = _text(binding.get("segment_field"))
    group_field = _text(binding.get("group_field"))
    group_a = binding.get("group_a")
    group_b = binding.get("group_b")
    values_a = [
        _number(row[outcome]) for row in rows
        if row.get(segment_field) == segment
        and row.get(group_field) == group_a
        and row.get(outcome) not in (None, "")
    ]
    values_b = [
        _number(row[outcome]) for row in rows
        if row.get(segment_field) == segment
        and row.get(group_field) == group_b
        and row.get(outcome) not in (None, "")
    ]
    sufficient = len(values_a) >= minimum_group_n and len(values_b) >= minimum_group_n
    item: dict[str, Any] = {
        "subgroup": segment,
        "group_a_n": len(values_a),
        "group_b_n": len(values_b),
        "support_status": "sufficient" if sufficient else "insufficient",
    }
    if sufficient:
        mean_a = statistics.fmean(values_a)
        mean_b = statistics.fmean(values_b)
        difference = mean_a - mean_b
        standard_error = math.sqrt(
            statistics.variance(values_a) / len(values_a)
            + statistics.variance(values_b) / len(values_b)
        )
        item.update({
            "group_a_mean": _round(mean_a),
            "group_b_mean": _round(mean_b),
            "difference": _round(difference),
            "difference_standard_error": _round(standard_error),
            "normal_approx_95_interval": [
                _round(difference - 1.96 * standard_error),
                _round(difference + 1.96 * standard_error),
            ],
        })
    return item


def _run_honest_heterogeneity(
    rows: list[dict[str, Any]], source: dict[str, Any], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    try:
        selected, window = _selected_rows(rows, source, binding)
        split_field = _text(binding.get("split_field"))
        unit_id_field = _text(binding.get("unit_id_field"))
        discovery_value = binding.get("discovery_value")
        estimation_value = binding.get("estimation_value")
        discovery_rows = [row for row in selected if row.get(split_field) == discovery_value]
        estimation_rows = [row for row in selected if row.get(split_field) == estimation_value]
        if not discovery_rows or not estimation_rows:
            raise ExperimentError("honest heterogeneity requires non-empty discovery and estimation samples")
        for label, sample in (("discovery", discovery_rows), ("estimation", estimation_rows)):
            if any(row.get(unit_id_field) in (None, "") for row in sample):
                raise ExperimentError(f"{label} sample contains a missing unit_id")
        discovery_units = {str(row.get(unit_id_field)) for row in discovery_rows}
        estimation_units = {str(row.get(unit_id_field)) for row in estimation_rows}
        overlapping_units = discovery_units & estimation_units
        if overlapping_units:
            raise ExperimentError(
                f"honest split is contaminated by {len(overlapping_units)} unit_id values present in both samples"
            )
        segment_field = _text(binding.get("segment_field"))
        observed_segments = sorted(
            {
                row.get(segment_field) for row in discovery_rows
                if row.get(segment_field) not in (None, "")
            },
            key=lambda value: str(value),
        )
        discovery_candidates = [
            _mean_difference_item(
                discovery_rows, binding, segment, int(binding["discovery_min_group_n"])
            )
            for segment in observed_segments
        ]
        threshold = float(binding["discovery_min_abs_difference"])
        eligible = [
            item for item in discovery_candidates
            if item["support_status"] == "sufficient"
            and abs(float(item["difference"])) >= threshold
        ]
        ranked = sorted(
            eligible,
            key=lambda item: (-abs(float(item["difference"])), str(item["subgroup"])),
        )
        frozen = ranked[: int(binding["max_selected_subgroups"])]
        selected_subgroups = [item["subgroup"] for item in frozen]
        estimation_results: list[dict[str, Any]] = []
        for discovery_item in frozen:
            estimate = _mean_difference_item(
                estimation_rows,
                binding,
                discovery_item["subgroup"],
                int(binding["estimation_min_group_n"]),
            )
            estimate["discovery_difference"] = discovery_item["difference"]
            if estimate["support_status"] == "sufficient":
                discovery_difference = float(discovery_item["difference"])
                estimation_difference = float(estimate["difference"])
                interval = estimate["normal_approx_95_interval"]
                same_direction = (
                    discovery_difference > 0 and estimation_difference > 0
                ) or (
                    discovery_difference < 0 and estimation_difference < 0
                )
                excludes_zero = float(interval[0]) > 0 or float(interval[1]) < 0
                estimate.update({
                    "same_direction_as_discovery": same_direction,
                    "interval_excludes_zero": excludes_zero,
                    "confirmation_status": (
                        "confirmed" if same_direction and excludes_zero else "not_confirmed"
                    ),
                })
            else:
                estimate["confirmation_status"] = "insufficient"
            estimation_results.append(estimate)
        estimable = [
            item for item in estimation_results if item["support_status"] == "sufficient"
        ]
        confirmed = [
            item for item in estimation_results if item["confirmation_status"] == "confirmed"
        ]
        enough_estimable = len(estimable) >= 2
        minimum_confirmed = int(binding["minimum_confirmed_subgroups"])
        heterogeneity_confirmed = len(confirmed) >= minimum_confirmed
        estimation_differences = [float(item["difference"]) for item in estimable]
        result = {
            "primary_value": {
                "selected_subgroup_count": len(selected_subgroups),
                "estimable_subgroup_count": len(estimable),
                "confirmed_subgroup_count": len(confirmed),
                "minimum_confirmed_subgroups": minimum_confirmed,
                "heterogeneity_confirmation": (
                    "confirmed" if heterogeneity_confirmed else "not_confirmed"
                ),
                "estimation_effect_spread": (
                    _round(max(estimation_differences) - min(estimation_differences))
                    if enough_estimable else None
                ),
                "estimation_opposite_directions": (
                    min(estimation_differences) < 0 < max(estimation_differences)
                    if enough_estimable else None
                ),
            },
            "evaluation_window": window,
            "split_audit": {
                "split_field": split_field,
                "discovery_value": discovery_value,
                "estimation_value": estimation_value,
                "discovery_row_count": len(discovery_rows),
                "estimation_row_count": len(estimation_rows),
                "discovery_unit_count": len(discovery_units),
                "estimation_unit_count": len(estimation_units),
                "overlapping_unit_count": 0,
                "ignored_row_count": len(selected) - len(discovery_rows) - len(estimation_rows),
            },
            "discovery_candidates": discovery_candidates,
            "selected_subgroups": selected_subgroups,
            "estimation_results": estimation_results,
            "selection_rule": {
                "metric": "absolute_difference",
                "minimum_absolute_difference": binding["discovery_min_abs_difference"],
                "maximum_selected_subgroups": binding["max_selected_subgroups"],
            },
            "confirmation_rule": binding["confirmation_rule"],
            "uncertainty_boundary": "Selection and estimation use non-overlapping units. Estimation intervals use an unadjusted normal approximation and do not correct for multiple selected subgroups.",
            "claim_boundary": (
                "A failed estimation-sample confirmation is reported as no confirmed heterogeneity; discovery-sample rank is never treated as confirmation. Descriptive contrasts are not individualized causal effects."
                if binding.get("effect_scope") == "descriptive"
                else "Causal interpretation remains limited to the separately verified identification design; honest sample splitting only separates subgroup discovery from effect estimation."
            ),
        }
        return "completed" if enough_estimable else "inconclusive", result, []
    except (ExperimentError, TypeError, ValueError, KeyError) as exc:
        return "unverifiable", {}, [str(exc)]


def _run_mechanism(
    rows: list[dict[str, Any]], source: dict[str, Any], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    if not _granularity_sufficient(
        _text(source.get("granularity")), _text(binding.get("required_granularity"))
    ):
        return "unverifiable", {}, ["available data is coarser than the mechanism test requires"]
    try:
        selected, window = _filter_window(
            rows, _text(source.get("time_field")), binding.get("evaluation_window")
        )
        measurement = _measure(
            selected, binding.get("measurement"), _text(source.get("time_field"))
        )
        predictions = binding.get("hypothesis_predictions") or {}
        matches = {
            hypothesis_id: _predicate(measurement.get("value"), predicate)
            for hypothesis_id, predicate in predictions.items()
        }
        supported = sorted(hypothesis_id for hypothesis_id, matched in matches.items() if matched)
        baseline_id = _text(binding.get("baseline_hypothesis_id"))
        candidate_id = _text(binding.get("candidate_hypothesis_id"))
        if supported == [candidate_id]:
            conclusion = "supports_candidate"
            coverage = "completed"
        elif supported == [baseline_id]:
            conclusion = "supports_baseline"
            coverage = "completed"
        else:
            conclusion = "mixed"
            coverage = "inconclusive"
        return coverage, {
            "primary_value": {
                "evidence_direction": conclusion,
                "measured_value": measurement.get("value"),
            },
            "evaluation_window": window,
            "measurement": measurement,
            "prediction_matches": matches,
            "supported_hypothesis_ids": supported,
            "discriminated": coverage == "completed",
            "claim_boundary": "A discriminating result supports one frozen explanation over another in this design; it does not validate every link in a causal story.",
        }, []
    except (ExperimentError, TypeError, ValueError) as exc:
        return "unverifiable", {}, [str(exc)]


def _linear_prediction(history: list[float], target_index: int) -> float:
    n = len(history)
    if n < 2:
        raise ExperimentError("linear_trend requires at least two observations")
    mean_x = (n - 1) / 2
    mean_y = statistics.fmean(history)
    denominator = sum((index - mean_x) ** 2 for index in range(n))
    if denominator == 0:
        return mean_y
    slope = sum(
        (index - mean_x) * (value - mean_y) for index, value in enumerate(history)
    ) / denominator
    intercept = mean_y - slope * mean_x
    return intercept + slope * target_index


def _model_prediction(
    values: list[float], origin: int, target: int, model: dict[str, Any]
) -> float:
    kind = _text(model.get("kind"))
    history = values[: origin + 1]
    if kind == "last_observation":
        return history[-1]
    if kind == "rolling_mean":
        window = int(model["window"])
        if len(history) < window:
            raise ExperimentError("insufficient history for rolling_mean")
        return statistics.fmean(history[-window:])
    if kind == "linear_trend":
        return _linear_prediction(history, target)
    if kind == "seasonal_naive":
        source_index = target - int(model["season_length"])
        if source_index < 0 or source_index > origin:
            raise ExperimentError("seasonal_naive cannot predict this target without future data")
        return values[source_index]
    raise ExperimentError(f"unsupported model kind:{kind}")


def _metric(errors: list[float], metric: str) -> float:
    if metric == "mae":
        return statistics.fmean(abs(error) for error in errors)
    return math.sqrt(statistics.fmean(error * error for error in errors))


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ExperimentError("cannot compute a percentile from an empty sample")
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _circular_block_mean_interval(
    values: list[float],
    *,
    confidence_level: float,
    replicates: int,
    seed: int,
    block_length: int,
) -> list[float]:
    n = len(values)
    if block_length > n:
        raise ExperimentError("block_length cannot exceed the number of common rolling origins")
    generator = random.Random(seed)
    bootstrap_means: list[float] = []
    blocks_needed = math.ceil(n / block_length)
    for _ in range(replicates):
        sampled: list[float] = []
        for _ in range(blocks_needed):
            start = generator.randrange(n)
            sampled.extend(values[(start + offset) % n] for offset in range(block_length))
        bootstrap_means.append(statistics.fmean(sampled[:n]))
    alpha = 1 - confidence_level
    return [
        _round(_percentile(bootstrap_means, alpha / 2)),
        _round(_percentile(bootstrap_means, 1 - alpha / 2)),
    ]


def _run_prediction(
    rows: list[dict[str, Any]], source: dict[str, Any], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    try:
        time_field = _text(binding.get("time_field"))
        if _text(source.get("time_field")) != time_field:
            raise ExperimentError("prediction time_field must match data_source.time_field")
        ordered = _ordered(rows, time_field)
        pairs = [
            (row, _number(row[binding["outcome_field"]]))
            for row in ordered
            if row.get(binding["outcome_field"]) not in (None, "")
        ]
        timestamps = [_text(row.get(time_field)) for row, _ in pairs]
        if not timestamps or any(not value for value in timestamps) or len(timestamps) != len(set(timestamps)):
            raise ExperimentError("prediction competition requires one usable observation per unique timestamp")
        values = [value for _, value in pairs]
        horizon = int(binding["horizon_steps"])
        minimum_history = int(binding["minimum_history"])
        models = binding["model_specs"]
        if len(values) < minimum_history + horizon + 1:
            raise ExperimentError("not enough observations for model competition")
        records: list[dict[str, Any]] = []
        model_errors: dict[str, list[float]] = {model["model_id"]: [] for model in models}
        for origin in range(minimum_history - 1, len(values) - horizon):
            target = origin + horizon
            predictions: dict[str, float] = {}
            try:
                for model in models:
                    predictions[model["model_id"]] = _model_prediction(values, origin, target, model)
            except ExperimentError:
                continue
            observed = values[target]
            for model_id, predicted in predictions.items():
                model_errors[model_id].append(predicted - observed)
            records.append({
                "origin_time": timestamps[origin],
                "target_time": timestamps[target],
                "observed": _round(observed),
                "predictions": {key: _round(value) for key, value in predictions.items()},
            })
        if len(records) < 2:
            raise ExperimentError("fewer than two common rolling origins are available to every model")
        metric_name = _text(binding.get("metric")).lower()
        scores = {
            model_id: _round(_metric(errors, metric_name))
            for model_id, errors in model_errors.items()
        }
        ranked = sorted(scores, key=lambda model_id: (float(scores[model_id]), model_id))
        baseline_id = _text(binding.get("baseline_model_id"))
        candidate_ids = [model_id for model_id in ranked if model_id != baseline_id]
        best_candidate = candidate_ids[0]
        baseline_score = float(scores[baseline_id])
        candidate_score = float(scores[best_candidate])
        if baseline_score == 0:
            improvement = 0.0 if candidate_score == 0 else -math.inf
        else:
            improvement = (baseline_score - candidate_score) / abs(baseline_score)
        minimum_improvement = float(binding.get("minimum_improvement"))
        finite_improvement = None if not math.isfinite(improvement) else _round(improvement)
        baseline_errors = model_errors[baseline_id]
        baseline_losses = (
            [abs(value) for value in baseline_errors]
            if metric_name == "mae"
            else [value * value for value in baseline_errors]
        )
        use_uncertainty = binding.get("uncertainty_method") == "circular_block_bootstrap"
        minimum_origins = int(binding.get("minimum_origins", 2))
        requested_confidence = float(binding.get("confidence_level", 0.95))
        per_comparison_confidence = 1 - (
            (1 - requested_confidence) / max(1, len(candidate_ids))
        )
        configured_block_length = int(binding.get("block_length", 1))
        enough_origins = (
            len(records) >= minimum_origins
            and (not use_uncertainty or configured_block_length <= len(records))
        )
        comparisons: list[dict[str, Any]] = []
        for candidate_index, model_id in enumerate(candidate_ids):
            candidate_errors = model_errors[model_id]
            candidate_losses = (
                [abs(value) for value in candidate_errors]
                if metric_name == "mae"
                else [value * value for value in candidate_errors]
            )
            paired_advantages = [
                baseline_loss - candidate_loss
                for baseline_loss, candidate_loss in zip(baseline_losses, candidate_losses)
            ]
            candidate_model_score = float(scores[model_id])
            candidate_improvement = (
                0.0 if baseline_score == 0 and candidate_model_score == 0
                else -math.inf if baseline_score == 0
                else (baseline_score - candidate_model_score) / abs(baseline_score)
            )
            interval = None
            if use_uncertainty and configured_block_length <= len(records):
                interval = _circular_block_mean_interval(
                    paired_advantages,
                    confidence_level=per_comparison_confidence,
                    replicates=int(binding["bootstrap_replicates"]),
                    seed=int(binding["bootstrap_seed"]) + candidate_index,
                    block_length=configured_block_length,
                )
            comparisons.append({
                "candidate_model_id": model_id,
                "candidate_score": scores[model_id],
                "relative_improvement": (
                    _round(candidate_improvement) if math.isfinite(candidate_improvement) else None
                ),
                "mean_baseline_minus_candidate_loss": _round(statistics.fmean(paired_advantages)),
                "mean_loss_difference_interval": interval,
                "candidate_win_count": sum(value > 0 for value in paired_advantages),
                "tie_count": sum(
                    math.isclose(value, 0.0, rel_tol=1e-12, abs_tol=1e-12)
                    for value in paired_advantages
                ),
                "baseline_win_count": sum(value < 0 for value in paired_advantages),
            })
        best_comparison = next(
            item for item in comparisons if item["candidate_model_id"] == best_candidate
        )
        point_clears = candidate_score < baseline_score and improvement >= minimum_improvement
        interval_clears = (
            not use_uncertainty
            or (
                isinstance(best_comparison["mean_loss_difference_interval"], list)
                and float(best_comparison["mean_loss_difference_interval"][0]) > 0
            )
        )
        if not enough_origins:
            conclusion = "insufficient_origins"
            selected_model = baseline_id
        elif point_clears and interval_clears:
            conclusion = "candidate_wins"
            selected_model = best_candidate
        elif point_clears and not interval_clears:
            conclusion = "uncertain_difference"
            selected_model = baseline_id
        elif math.isclose(candidate_score, baseline_score, rel_tol=1e-12, abs_tol=1e-12):
            conclusion = "tie"
            selected_model = baseline_id
        else:
            conclusion = "baseline_wins_or_gain_below_threshold"
            selected_model = baseline_id
        legacy_best = {
            "mean_baseline_minus_candidate_loss": best_comparison["mean_baseline_minus_candidate_loss"],
            "candidate_win_count": best_comparison["candidate_win_count"],
            "tie_count": best_comparison["tie_count"],
            "baseline_win_count": best_comparison["baseline_win_count"],
            "inference_boundary": (
                "See uncertainty for the paired circular-block interval."
                if use_uncertainty
                else "This is a paired descriptive loss comparison, not a significance test."
            ),
        }
        return "completed" if enough_origins else "inconclusive", {
            "primary_value": {
                "selected_model_id": selected_model,
                "baseline_score": _round(baseline_score),
                "best_candidate_model_id": best_candidate,
                "best_candidate_score": _round(candidate_score),
                "relative_improvement": finite_improvement,
                "comparison_result": conclusion,
            },
            "metric": metric_name,
            "model_scores": scores,
            "ranked_model_ids": ranked,
            "prediction_count": len(records),
            "minimum_origins": minimum_origins,
            "paired_loss_comparisons": comparisons,
            "paired_loss_comparison": legacy_best,
            "uncertainty": {
                "method": binding.get("uncertainty_method") or "none",
                "familywise_confidence_level": binding.get("confidence_level"),
                "per_comparison_confidence_level": (
                    _round(per_comparison_confidence) if use_uncertainty else None
                ),
                "bootstrap_replicates": binding.get("bootstrap_replicates"),
                "bootstrap_seed": binding.get("bootstrap_seed"),
                "block_length": binding.get("block_length"),
                "inference_boundary": (
                    "Circular moving-block percentile intervals use a Bonferroni-adjusted per-comparison confidence level. They are conditional on weak local dependence, the frozen origins, loss, block length, and model set; they are not universal model-significance claims."
                    if use_uncertainty
                    else "Legacy contract 0.1 provides a paired descriptive comparison only."
                ),
            },
            "predictions": records,
            "leakage_check": "every model was fit only on values at or before the recorded rolling origin",
            "claim_boundary": "The selected model is preferred only for the frozen horizon, metric, origins, and minimum-improvement threshold.",
        }, []
    except (ExperimentError, TypeError, ValueError, KeyError) as exc:
        return "unverifiable", {}, [str(exc)]


def _aggregate(values: list[float], kind: str) -> float:
    if kind == "sum":
        return sum(values)
    if kind == "mean":
        return statistics.fmean(values)
    if kind == "min":
        return min(values)
    return max(values)


def _policy_records(
    rows: list[dict[str, Any]], binding: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    action_values = binding["action_values"]
    action_field = binding["logged_action_field"]
    propensity_field = binding["propensity_field"]
    reward_field = binding["reward_field"]
    bootstrap_unit_field = binding["bootstrap_unit_field"]
    policy_type = policy["policy_type"]
    probability_fields = policy.get("action_probability_fields") or {}
    use_dr = "doubly_robust" in binding["estimators"]
    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        action = _text(row.get(action_field))
        if action not in action_values:
            raise ExperimentError(
                f"row {row_number} has a logged action outside action_values"
            )
        bootstrap_unit = _text(row.get(bootstrap_unit_field))
        if not bootstrap_unit:
            raise ExperimentError(f"row {row_number} has a missing bootstrap unit")
        propensity = _number(row.get(propensity_field))
        if not 0 < propensity <= 1:
            raise ExperimentError("logging propensities must be in (0, 1]")
        if policy_type == "logging_policy":
            target_probability = propensity
        elif policy_type == "uniform_policy":
            target_probability = 1 / len(action_values)
        else:
            probabilities = [
                _number(row.get(probability_fields[action_value]))
                for action_value in action_values
            ]
            if any(value < 0 or value > 1 for value in probabilities):
                raise ExperimentError("target-policy probabilities must be between 0 and 1")
            if not math.isclose(sum(probabilities), 1.0, rel_tol=1e-7, abs_tol=1e-7):
                raise ExperimentError("target-policy probabilities must sum to 1 on every row")
            target_probability = _number(row.get(probability_fields[action]))
        record = {
            "reward": _number(row.get(reward_field)),
            "logging_propensity": propensity,
            "target_probability": target_probability,
            "bootstrap_unit": bootstrap_unit,
        }
        if use_dr:
            record["q_logged"] = _number(row.get(binding["q_logged_field"]))
            record["q_policy"] = _number(row.get(policy["q_policy_field"]))
        records.append(record)
    return records


def _estimate_policy_value(
    records: list[dict[str, Any]],
    estimator: str,
    *,
    weight_clip: float | None = None,
    propensity_floor: float | None = None,
) -> tuple[float, list[float]]:
    weights = [
        min(
            record["target_probability"]
            / max(record["logging_propensity"], propensity_floor or 0.0),
            weight_clip if weight_clip is not None else math.inf,
        )
        for record in records
    ]
    if estimator == "ips":
        value = statistics.fmean(
            weight * record["reward"] for weight, record in zip(weights, records)
        )
    elif estimator == "snips":
        denominator = sum(weights)
        if denominator <= 0:
            raise ExperimentError("SNIPS is undefined because the policy has no logged support")
        value = sum(
            weight * record["reward"] for weight, record in zip(weights, records)
        ) / denominator
    else:
        value = statistics.fmean(
            record["q_policy"] + weight * (record["reward"] - record["q_logged"])
            for weight, record in zip(weights, records)
        )
    return value, weights


def _cluster_effective_sample_size(
    weights: list[float], records: list[dict[str, Any]]
) -> float:
    by_unit: dict[str, float] = {}
    for weight, record in zip(weights, records):
        unit = str(record["bootstrap_unit"])
        by_unit[unit] = by_unit.get(unit, 0.0) + weight
    unit_weights = list(by_unit.values())
    denominator = sum(weight * weight for weight in unit_weights)
    return 0.0 if denominator == 0 else sum(unit_weights) ** 2 / denominator


def _bootstrap_policy_delta_interval(
    candidate: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    estimator: str,
    *,
    confidence_level: float,
    replicates: int,
    seed: int,
) -> tuple[list[float] | None, int]:
    if len(candidate) != len(baseline):
        raise ExperimentError("candidate and baseline policy records must cover identical rows")
    generator = random.Random(seed)
    deltas: list[float] = []
    units: dict[str, list[int]] = {}
    for index, (candidate_row, baseline_row) in enumerate(zip(candidate, baseline)):
        candidate_unit = str(candidate_row["bootstrap_unit"])
        if candidate_unit != str(baseline_row["bootstrap_unit"]):
            raise ExperimentError("candidate and baseline bootstrap units are not aligned")
        units.setdefault(candidate_unit, []).append(index)
    unit_ids = sorted(units)
    n_units = len(unit_ids)
    for _ in range(replicates):
        sampled_units = [unit_ids[generator.randrange(n_units)] for _ in range(n_units)]
        indices = [index for unit in sampled_units for index in units[unit]]
        candidate_sample = [candidate[index] for index in indices]
        baseline_sample = [baseline[index] for index in indices]
        try:
            candidate_value, _ = _estimate_policy_value(candidate_sample, estimator)
            baseline_value, _ = _estimate_policy_value(baseline_sample, estimator)
        except ExperimentError:
            continue
        deltas.append(candidate_value - baseline_value)
    if len(deltas) < math.ceil(replicates * 0.8):
        return None, len(deltas)
    alpha = 1 - confidence_level
    return [
        _round(_percentile(deltas, alpha / 2)),
        _round(_percentile(deltas, 1 - alpha / 2)),
    ], len(deltas)


def _run_offline_policy_evaluation(
    rows: list[dict[str, Any]], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    try:
        if not rows:
            raise ExperimentError("offline policy evaluation requires at least one logged row")
        policies = binding["policy_specs"]
        policy_records = {
            policy["policy_id"]: _policy_records(rows, binding, policy)
            for policy in policies
        }
        estimators = binding["estimators"]
        primary_estimator = binding["primary_estimator"]
        minimum_ess = float(binding["minimum_effective_sample_size"])
        maximum_weight = float(binding["maximum_importance_weight"])
        evaluations: list[dict[str, Any]] = []
        for policy in policies:
            policy_id = policy["policy_id"]
            records = policy_records[policy_id]
            values: dict[str, float] = {}
            raw_weights: list[float] | None = None
            for estimator in estimators:
                value, estimator_weights = _estimate_policy_value(records, estimator)
                values[estimator] = _round(value)
                if raw_weights is None:
                    raw_weights = estimator_weights
            weights = raw_weights or []
            ess = _cluster_effective_sample_size(weights, records)
            max_observed_weight = max(weights) if weights else 0.0
            independent_units = {str(record["bootstrap_unit"]) for record in records}
            positive_units = {
                str(record["bootstrap_unit"]) for weight, record in zip(weights, records)
                if weight > 0
            }
            evaluations.append({
                "policy_id": policy_id,
                "estimated_values": values,
                "effective_sample_size": _round(ess),
                "maximum_observed_importance_weight": _round(max_observed_weight),
                "positive_weight_row_count": sum(weight > 0 for weight in weights),
                "independent_unit_count": len(independent_units),
                "positive_weight_unit_count": len(positive_units),
                "overlap_status": (
                    "supported"
                    if ess >= minimum_ess and max_observed_weight <= maximum_weight
                    else "failed"
                ),
            })
        by_policy = {item["policy_id"]: item for item in evaluations}
        baseline_id = binding["baseline_action"]
        fallback_id = binding["fallback_action"]
        candidate_ids = [
            policy_id for policy_id in binding["action_options"] if policy_id != baseline_id
        ]
        best_candidate = sorted(
            candidate_ids,
            key=lambda policy_id: (
                -float(by_policy[policy_id]["estimated_values"][primary_estimator]),
                policy_id,
            ),
        )[0]
        baseline_value = float(by_policy[baseline_id]["estimated_values"][primary_estimator])
        candidate_value = float(by_policy[best_candidate]["estimated_values"][primary_estimator])
        advantage = candidate_value - baseline_value
        requested_confidence = float(binding["confidence_level"])
        per_comparison_confidence = 1 - (
            (1 - requested_confidence) / max(1, len(candidate_ids))
        )
        policy_comparisons: list[dict[str, Any]] = []
        for candidate_index, policy_id in enumerate(candidate_ids):
            policy_value = float(
                by_policy[policy_id]["estimated_values"][primary_estimator]
            )
            interval, valid_replicates = _bootstrap_policy_delta_interval(
                policy_records[policy_id],
                policy_records[baseline_id],
                primary_estimator,
                confidence_level=per_comparison_confidence,
                replicates=int(binding["bootstrap_replicates"]),
                seed=int(binding["bootstrap_seed"]) + candidate_index,
            )
            policy_comparisons.append({
                "candidate_policy_id": policy_id,
                "advantage_over_baseline": _round(policy_value - baseline_value),
                "advantage_interval": interval,
                "valid_bootstrap_replicates": valid_replicates,
            })
        best_comparison = next(
            item for item in policy_comparisons
            if item["candidate_policy_id"] == best_candidate
        )
        interval = best_comparison["advantage_interval"]
        estimator_stability: list[dict[str, Any]] = []
        estimator_agreement = True
        for estimator in estimators:
            estimator_values = {
                policy_id: float(by_policy[policy_id]["estimated_values"][estimator])
                for policy_id in by_policy
            }
            ranked = sorted(
                estimator_values,
                key=lambda policy_id: (-estimator_values[policy_id], policy_id),
            )
            estimator_advantage = (
                estimator_values[best_candidate] - estimator_values[baseline_id]
            )
            estimator_stable = (
                ranked[0] == best_candidate
                and estimator_advantage >= float(binding["minimum_advantage"])
            )
            estimator_agreement = estimator_agreement and estimator_stable
            estimator_stability.append({
                "estimator": estimator,
                "best_policy_id": ranked[0],
                "candidate_advantage_over_baseline": _round(estimator_advantage),
                "selected_candidate_stable": estimator_stable,
            })
        sensitivity_results: list[dict[str, Any]] = []
        sensitivity_stable = True
        for estimator in estimators:
            for clip in binding["weight_clip_grid"]:
                for floor in binding["propensity_floor_grid"]:
                    scenario_values: dict[str, float] = {}
                    for policy_id, records in policy_records.items():
                        value, _ = _estimate_policy_value(
                            records,
                            estimator,
                            weight_clip=float(clip),
                            propensity_floor=float(floor),
                        )
                        scenario_values[policy_id] = value
                    ranked = sorted(
                        scenario_values,
                        key=lambda policy_id: (-scenario_values[policy_id], policy_id),
                    )
                    scenario_advantage = (
                        scenario_values[best_candidate] - scenario_values[baseline_id]
                    )
                    scenario_stable = (
                        ranked[0] == best_candidate
                        and scenario_advantage >= float(binding["minimum_advantage"])
                    )
                    sensitivity_stable = sensitivity_stable and scenario_stable
                    sensitivity_results.append({
                        "estimator": estimator,
                        "weight_clip": clip,
                        "propensity_floor": floor,
                        "best_policy_id": ranked[0],
                        "candidate_advantage_over_baseline": _round(scenario_advantage),
                        "selected_candidate_stable": scenario_stable,
                    })
        overlap_supported = (
            by_policy[best_candidate]["overlap_status"] == "supported"
            and by_policy[baseline_id]["overlap_status"] == "supported"
            and by_policy[fallback_id]["overlap_status"] == "supported"
        )
        interval_clears = (
            isinstance(interval, list)
            and float(interval[0]) > float(binding["minimum_advantage"])
        )
        stable = estimator_agreement and sensitivity_stable
        clears = (
            advantage >= float(binding["minimum_advantage"])
            and interval_clears
            and overlap_supported
            and stable
        )
        selected = best_candidate if clears else fallback_id
        if clears:
            status = "policy_selected"
            failure_reasons: list[str] = []
        else:
            status = "fallback_selected"
            failure_reasons = []
            if advantage < float(binding["minimum_advantage"]):
                failure_reasons.append("point_advantage_below_threshold")
            if not interval_clears:
                failure_reasons.append("advantage_interval_does_not_clear_threshold")
            if not overlap_supported:
                failure_reasons.append("overlap_diagnostic_failed")
            if not estimator_agreement:
                failure_reasons.append("estimator_disagreement")
            if not sensitivity_stable:
                failure_reasons.append("sensitivity_result_unstable")
        fallback_supported = by_policy[fallback_id]["overlap_status"] == "supported"
        return "completed" if fallback_supported else "inconclusive", {
            "primary_value": {
                "selected_policy_id": selected if fallback_supported else None,
                "decision_status": status if fallback_supported else "unsupported_fallback",
                "best_candidate_policy_id": best_candidate,
                "best_candidate_advantage_over_baseline": _round(advantage),
                "advantage_interval": interval,
                "failure_reasons": failure_reasons,
            },
            "policies": evaluations,
            "policy_comparisons": policy_comparisons,
            "primary_estimator": primary_estimator,
            "minimum_advantage": binding["minimum_advantage"],
            "overlap_thresholds": {
                "minimum_effective_sample_size": binding["minimum_effective_sample_size"],
                "maximum_importance_weight": binding["maximum_importance_weight"],
            },
            "bootstrap": {
                "method": "clustered_units",
                "unit_field": binding["bootstrap_unit_field"],
                "familywise_confidence_level": binding["confidence_level"],
                "per_comparison_confidence_level": _round(per_comparison_confidence),
                "requested_replicates": binding["bootstrap_replicates"],
                "seed": binding["bootstrap_seed"],
            },
            "estimator_stability": estimator_stability,
            "sensitivity_results": sensitivity_results,
            "estimator_agreement": estimator_agreement,
            "sensitivity_stable": sensitivity_stable,
            "withdrawal_condition": binding["withdrawal_condition"],
            "identification_boundary": "IPS, SNIPS, and doubly robust estimates require correct logged propensities, consistency, and adequate overlap. Doubly robust estimation additionally relies on either the logging propensity or outcome model being correctly specified.",
            "sensitivity_boundary": "Weight clipping and propensity-floor scenarios diagnose dependence on observed overlap choices; stability across them does not rule out hidden confounding, policy drift, or reward measurement error.",
            "claim_boundary": "The selected policy is supported only for the logged population, declared policies, reward, overlap thresholds, estimators, and sensitivity grid. Failure of any selection condition returns the declared fallback.",
        }, []
    except (ExperimentError, TypeError, ValueError, KeyError) as exc:
        return "unverifiable", {}, [str(exc)]


def _run_decision(
    rows: list[dict[str, Any]], binding: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    try:
        actions = binding["action_options"]
        action_field = binding["action_field"]
        benefit_field = binding["benefit_field"]
        cost_field = binding["cost_field"]
        probability_field = _text(binding.get("probability_field"))
        weight_field = _text(binding.get("weight_field"))
        evaluations: list[dict[str, Any]] = []
        for action in actions:
            action_rows = [row for row in rows if _text(row.get(action_field)) == action]
            if not action_rows:
                raise ExperimentError(f"decision data has no rows for action:{action}")
            weighted_utility = 0.0
            total_weight = 0.0
            scenario_utilities: list[float] = []
            for row in action_rows:
                benefit = _number(row.get(benefit_field))
                cost = _number(row.get(cost_field))
                probability = _number(row.get(probability_field)) if probability_field else 1.0
                weight = _number(row.get(weight_field)) if weight_field else 1.0
                if not 0 <= probability <= 1:
                    raise ExperimentError("decision probabilities must be between 0 and 1")
                if weight <= 0:
                    raise ExperimentError("decision weights must be positive")
                scenario_utility = probability * benefit - cost
                scenario_utilities.append(scenario_utility)
                weighted_utility += weight * scenario_utility
                total_weight += weight
            expected_net_utility = weighted_utility / total_weight
            constraint_results: list[dict[str, Any]] = []
            for rule in binding.get("constraint_rules") or []:
                values = [_number(row.get(rule["field"])) for row in action_rows]
                observed = _aggregate(values, rule["aggregation"])
                predicate = {"operator": rule["operator"], "value": rule["value"]}
                if rule.get("tolerance") is not None:
                    predicate["tolerance"] = rule["tolerance"]
                passed = _predicate(observed, predicate)
                constraint_results.append({
                    "field": rule["field"],
                    "aggregation": rule["aggregation"],
                    "observed": _round(observed),
                    "operator": rule["operator"],
                    "threshold": rule["value"],
                    "passed": passed,
                })
            evaluations.append({
                "action": action,
                "scenario_count": len(action_rows),
                "expected_net_utility": _round(expected_net_utility),
                "scenario_net_utility_range": [
                    _round(min(scenario_utilities)), _round(max(scenario_utilities))
                ],
                "constraints": constraint_results,
                "feasible": all(item["passed"] for item in constraint_results),
            })
        by_action = {item["action"]: item for item in evaluations}
        feasible = [item for item in evaluations if item["feasible"]]
        fallback = binding["fallback_action"]
        baseline = binding["baseline_action"]
        if not feasible or not by_action[fallback]["feasible"]:
            return "inconclusive", {
                "primary_value": {"selected_action": None, "decision_status": "no_feasible_fallback"},
                "actions": evaluations,
                "withdrawal_condition": binding["withdrawal_condition"],
                "claim_boundary": "No action is authorized because a feasible fallback is unavailable.",
            }, []
        best = sorted(
            feasible, key=lambda item: (-float(item["expected_net_utility"]), item["action"])
        )[0]
        baseline_utility = float(by_action[baseline]["expected_net_utility"])
        advantage = float(best["expected_net_utility"]) - baseline_utility
        clears = (
            float(best["expected_net_utility"]) >= float(binding["minimum_net_utility"])
            and advantage >= float(binding["minimum_advantage"])
        )
        selected = best["action"] if clears else fallback
        decision_status = "action_selected" if clears else "fallback_selected"
        return "completed", {
            "primary_value": {
                "selected_action": selected,
                "decision_status": decision_status,
                "selected_expected_net_utility": by_action[selected]["expected_net_utility"],
                "best_action": best["action"],
                "best_action_advantage_over_baseline": _round(advantage),
                "utility_margin": _round(
                    float(best["expected_net_utility"]) - float(binding["minimum_net_utility"])
                ),
                "advantage_margin": _round(
                    advantage - float(binding["minimum_advantage"])
                ),
            },
            "actions": evaluations,
            "minimum_net_utility": binding["minimum_net_utility"],
            "minimum_advantage": binding["minimum_advantage"],
            "withdrawal_condition": binding["withdrawal_condition"],
            "claim_boundary": "The selected action is valid only for the frozen utility formula, scenarios, constraints, thresholds, and withdrawal condition.",
        }, []
    except (ExperimentError, TypeError, ValueError, KeyError) as exc:
        return "unverifiable", {}, [str(exc)]


def run_deep_analysis_execution(spec: Any, base_dir: Path | None = None) -> dict[str, Any]:
    source, binding, errors = _validate_spec(spec)
    result_version = (
        LEGACY_RESULT_VERSION
        if isinstance(spec, dict) and spec.get("contract_version") == LEGACY_SPEC_VERSION
        else RESULT_VERSION
    )
    base = {
        "contract_version": result_version,
        "source_spec": copy.deepcopy(spec) if isinstance(spec, dict) else None,
        "execution_id": _text(spec.get("execution_id")) if isinstance(spec, dict) else "",
        "decision_question": _text(spec.get("decision_question")) if isinstance(spec, dict) else "",
        "analysis_binding": copy.deepcopy(binding) if binding else None,
        "data_evidence_refs": copy.deepcopy(spec.get("data_evidence_refs")) if isinstance(spec, dict) else None,
    }
    if errors:
        return {
            **base, "execution_status": "invalid_spec", "coverage_status": "unverifiable",
            "errors": errors, "data_profile": None, "result": None,
        }
    try:
        rows, data_profile = _load_rows(source, base_dir)
    except ExperimentError as exc:
        return {
            **base, "execution_status": "unverifiable", "coverage_status": "unverifiable",
            "errors": [str(exc)], "data_profile": None, "result": None,
        }
    layer = binding["analysis_layer"]
    if layer == "heterogeneity":
        if binding["method"] == "honest_subgroup_mean_difference":
            coverage, result, run_errors = _run_honest_heterogeneity(rows, source, binding)
        else:
            coverage, result, run_errors = _run_heterogeneity(rows, source, binding)
    elif layer == "mechanism":
        coverage, result, run_errors = _run_mechanism(rows, source, binding)
    elif layer == "predictive":
        coverage, result, run_errors = _run_prediction(rows, source, binding)
    else:
        if binding["method"] == "offline_policy_value_sensitivity":
            coverage, result, run_errors = _run_offline_policy_evaluation(rows, binding)
        else:
            coverage, result, run_errors = _run_decision(rows, binding)
    execution_status = "completed" if coverage in {"completed", "inconclusive"} else "unverifiable"
    return {
        **base,
        "execution_status": execution_status,
        "coverage_status": coverage,
        "errors": run_errors,
        "data_profile": data_profile,
        "result": result or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bound heterogeneity, direct-mechanism, forecast-competition, or policy-utility analysis."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = load_json(args.spec)
    protected_sources = [args.spec]
    source_path = str(((spec.get("data_source") or {}).get("path") or "")).strip() \
        if isinstance(spec, dict) else ""
    if source_path:
        data_path = Path(source_path)
        if not data_path.is_absolute():
            data_path = args.spec.resolve().parent / data_path
        protected_sources.append(data_path)
    guard_cli_output(parser, args.output, protected_sources)
    result = run_deep_analysis_execution(spec, args.spec.resolve().parent)
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "execution_status": result["execution_status"],
        "coverage_status": result["coverage_status"],
    }, ensure_ascii=False))
    return 0 if result["execution_status"] in {"completed", "unverifiable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
