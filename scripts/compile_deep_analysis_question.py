from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from compile_deep_findings import adapt_deep_evidence


SPEC_VERSION = "data-lens-deep-analysis-question/0.1"
RESULT_VERSION = "data-lens-deep-analysis-plan/0.1"
OBJECTIVES = {
    "describe",
    "compare",
    "diagnose",
    "explain",
    "predict",
    "estimate_effect",
    "choose_action",
}
READINESS = {"supported", "uncertain", "violated"}
ASSIGNMENT = {"randomized", "as_if_random", "observational", "unknown"}
DECISION_BASES = {"causal_effect", "prediction", "descriptive_rule"}
EDGE_RELATIONS = {
    "causes", "mediates", "confounds", "selects", "measures", "feeds_back", "associated_with"
}
IDENTIFICATION = {
    "randomized",
    "backdoor",
    "difference_in_differences",
    "interrupted_time_series",
    "regression_discontinuity",
    "instrumental_variable",
    "frontdoor",
    "none",
}
TIME_SAFE_VALIDATION = {"rolling_origin", "future_holdout"}
CROSS_SECTION_SAFE_VALIDATION = {"independent_holdout"}
LAYER_ORDER = (
    "measurement",
    "descriptive",
    "temporal",
    "heterogeneity",
    "mechanism",
    "causal",
    "predictive",
    "decision",
)
PREDICTION_MODEL_KINDS = {"last_observation", "rolling_mean", "linear_trend", "seasonal_naive"}
DECISION_CONSTRAINT_AGGREGATIONS = {"sum", "mean", "min", "max"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any, field: str, errors: list[str], *, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    output = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(output) != len(value):
        errors.append(f"{field} must contain non-empty strings")
    if required and not output:
        errors.append(f"{field} must not be empty")
    return output


def _layer(status: str, reason: str, requirements: list[str], methods: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "missing_requirements": list(dict.fromkeys(requirements)),
        "suggested_methods": list(dict.fromkeys(methods)),
    }


def _required_layers(
    objective: str,
    has_time: bool,
    has_prediction_design: bool,
    decision_basis: str,
) -> set[str]:
    required = {"measurement", "descriptive"}
    if has_time or objective in {"predict", "estimate_effect"} or decision_basis == "prediction":
        required.add("temporal")
    if objective in {"diagnose", "explain", "estimate_effect"} or decision_basis == "causal_effect":
        required.update({"heterogeneity", "mechanism"})
    elif objective in {"compare", "choose_action"}:
        required.add("heterogeneity")
    if objective == "estimate_effect" or decision_basis == "causal_effect":
        required.add("causal")
    if objective == "predict" or has_prediction_design or decision_basis == "prediction":
        required.add("predictive")
    if objective == "choose_action":
        required.add("decision")
    return required


def compile_deep_analysis_question(
    spec: Any,
    evidence_payload: Any = None,
    evidence_base_dir: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, dict) or spec.get("contract_version") != SPEC_VERSION:
        raise ValueError("unsupported deep analysis question contract")

    errors: list[str] = []
    warnings: list[str] = []
    decision_question = _text(spec.get("decision_question"))
    objective = _text(spec.get("objective"))
    if not decision_question:
        errors.append("decision_question is required")
    if objective not in OBJECTIVES:
        errors.append("objective is invalid")

    scope = spec.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
        scope = {}
    population = _text(scope.get("population"))
    analysis_unit = _text(scope.get("analysis_unit"))
    outcome = scope.get("outcome")
    if not isinstance(outcome, dict):
        errors.append("scope.outcome must be an object")
        outcome = {}
    for field, value in (
        ("scope.population", population),
        ("scope.analysis_unit", analysis_unit),
        ("scope.outcome.name", _text(outcome.get("name"))),
        ("scope.outcome.field", _text(outcome.get("field"))),
        ("scope.outcome.unit", _text(outcome.get("unit"))),
    ):
        if not value:
            errors.append(f"{field} is required")
    time_field = _text(scope.get("time_field"))
    time_granularity = _text(scope.get("time_granularity"))
    segments = _text_list(scope.get("segments"), "scope.segments", errors)

    readiness = spec.get("data_readiness")
    if not isinstance(readiness, dict):
        errors.append("data_readiness must be an object")
        readiness = {}
    evidence_refs = _text_list(
        readiness.get("evidence_refs"), "data_readiness.evidence_refs", errors, required=True
    )
    evidence_checked = evidence_payload is not None
    evidence_index: dict[str, dict[str, Any]] = {}
    if evidence_payload is not None:
        try:
            evidence_index = adapt_deep_evidence(evidence_payload, evidence_base_dir)
        except ValueError as exc:
            errors.append(f"evidence card set is invalid:{exc}")
    available_ids = set(evidence_index)
    verified_ids = {
        evidence_id for evidence_id, card in evidence_index.items() if card.get("verified") is True
    }
    if evidence_payload is not None:
        unknown_refs = sorted(set(evidence_refs) - available_ids)
        if unknown_refs:
            errors.append(f"unknown evidence references:{','.join(unknown_refs)}")
        unverified_refs = sorted((set(evidence_refs) & available_ids) - verified_ids)
        if unverified_refs:
            errors.append(f"unverified evidence references:{','.join(unverified_refs)}")
    else:
        warnings.append("evidence cards were not supplied; the plan can route work but cannot allow evidence-dependent claims")
    measurement_state = _text(readiness.get("stable_measurement"))
    if measurement_state not in READINESS:
        errors.append("data_readiness.stable_measurement is invalid")
    outcome_observed = readiness.get("outcome_observed") is True
    exposure_observed = readiness.get("exposure_observed") is True
    temporal_order_known = readiness.get("temporal_order_known") is True
    repeated_units = readiness.get("repeated_units") is True
    pre_post_periods = readiness.get("pre_post_periods") is True
    comparison_groups = readiness.get("comparison_groups") is True
    missingness_assessed = readiness.get("missingness_assessed") is True
    for field in (
        "outcome_observed",
        "exposure_observed",
        "temporal_order_known",
        "repeated_units",
        "pre_post_periods",
        "comparison_groups",
        "missingness_assessed",
    ):
        if not isinstance(readiness.get(field), bool):
            errors.append(f"data_readiness.{field} must be boolean")

    early_decision = spec.get("decision_design") if isinstance(spec.get("decision_design"), dict) else {}
    decision_basis = _text(early_decision.get("evidence_basis"))
    required = _required_layers(
        objective,
        bool(time_field),
        isinstance(spec.get("prediction_design"), dict),
        decision_basis,
    )
    layers: dict[str, dict[str, Any]] = {}

    measurement_missing: list[str] = []
    if not outcome_observed:
        measurement_missing.append("observed outcome")
    if measurement_state == "violated":
        measurement_missing.append("repair or replace the unstable measurement")
    if not missingness_assessed:
        measurement_missing.append("missingness assessment")
    if not evidence_checked:
        measurement_missing.append("verified evidence card set")
    if not outcome_observed or measurement_state == "violated":
        measurement_status = "blocked"
    elif measurement_state == "uncertain" or not missingness_assessed or not evidence_checked:
        measurement_status = "conditional"
    else:
        measurement_status = "ready"
    layers["measurement"] = _layer(
        measurement_status,
        "Measurement quality determines whether later numerical differences are interpretable.",
        measurement_missing,
        ["data_lens.table_profile", "data_lens.workbook_integrity"],
    )

    descriptive_status = "blocked" if not outcome_observed else (
        "conditional" if measurement_status == "conditional" else "ready"
    )
    layers["descriptive"] = _layer(
        descriptive_status,
        "Describe distributions, denominators, composition, missingness, and unusual observations before explanation.",
        [] if outcome_observed else ["observed outcome"],
        ["data_lens.grouped_descriptive", "data_lens.robust_anomaly_candidates"],
    )

    temporal_missing: list[str] = []
    if not time_field:
        temporal_missing.append("time field")
    if not time_granularity:
        temporal_missing.append("time granularity")
    if not temporal_order_known:
        temporal_missing.append("known temporal ordering")
    if temporal_missing or measurement_status == "blocked":
        temporal_status = "blocked"
        if measurement_status == "blocked":
            temporal_missing.append("usable measured outcome")
    elif not evidence_checked or measurement_status == "conditional":
        temporal_status = "conditional"
    else:
        temporal_status = "ready"
    if not evidence_checked:
        temporal_missing.append("verified temporal evidence")
    layers["temporal"] = _layer(
        temporal_status if "temporal" in required else "not_requested",
        "Separate trend, seasonality, local stages, turning points, and lead-lag candidates without treating them as causes.",
        temporal_missing if "temporal" in required else [],
        ["data_lens.change_point_candidate", "data_lens.deep_data_probes"],
    )

    heterogeneity = spec.get("heterogeneity_design")
    if heterogeneity is None:
        heterogeneity = {}
    if not isinstance(heterogeneity, dict):
        errors.append("heterogeneity_design must be an object")
        heterogeneity = {}
    heterogeneity_target = _text(heterogeneity.get("target"))
    segment_field = _text(heterogeneity.get("segment_field"))
    heterogeneity_group_field = _text(heterogeneity.get("group_field"))
    heterogeneity_group_a = heterogeneity.get("group_a")
    heterogeneity_group_b = heterogeneity.get("group_b")
    minimum_group_n = heterogeneity.get("minimum_group_n")
    effect_scope = _text(heterogeneity.get("effect_scope"))
    heterogeneity_validation_mode = _text(heterogeneity.get("validation_mode")) or "prespecified"
    split_field = _text(heterogeneity.get("split_field"))
    discovery_value = heterogeneity.get("discovery_value")
    estimation_value = heterogeneity.get("estimation_value")
    unit_id_field = _text(heterogeneity.get("unit_id_field"))
    discovery_min_group_n = heterogeneity.get("discovery_min_group_n")
    estimation_min_group_n = heterogeneity.get("estimation_min_group_n")
    discovery_min_abs_difference = heterogeneity.get("discovery_min_abs_difference")
    max_selected_subgroups = heterogeneity.get("max_selected_subgroups")
    minimum_confirmed_subgroups = heterogeneity.get("minimum_confirmed_subgroups")
    selection_metric = _text(heterogeneity.get("selection_metric"))
    confirmation_rule = _text(heterogeneity.get("confirmation_rule"))
    heterogeneity_design_refs = _text_list(
        heterogeneity.get("design_evidence_refs"),
        "heterogeneity_design.design_evidence_refs",
        errors,
    )
    heterogeneity_missing = [] if segments else ["at least one decision-relevant segment"]
    if not comparison_groups:
        heterogeneity_missing.append("comparable groups or cohorts")
    for value, label in (
        (heterogeneity_target, "heterogeneity target"),
        (segment_field, "segment field"),
        (heterogeneity_group_field, "comparison-group field"),
    ):
        if "heterogeneity" in required and not value:
            heterogeneity_missing.append(label)
    if "heterogeneity" in required and segment_field and segment_field not in segments:
        heterogeneity_missing.append("segment field declared in scope.segments")
    if "heterogeneity" in required and (
        heterogeneity_group_a in (None, "") or heterogeneity_group_b in (None, "")
    ):
        heterogeneity_missing.append("two comparison-group values")
    elif heterogeneity_group_a == heterogeneity_group_b and heterogeneity_group_a not in (None, ""):
        errors.append("heterogeneity_design requires distinct group_a and group_b")
        heterogeneity_missing.append("distinct comparison-group values")
    if heterogeneity_validation_mode not in {"prespecified", "honest_split"}:
        errors.append("heterogeneity_design.validation_mode is invalid")
    if "heterogeneity" in required and heterogeneity_validation_mode == "prespecified" and (
        not isinstance(minimum_group_n, int)
        or isinstance(minimum_group_n, bool)
        or minimum_group_n < 2
    ):
        heterogeneity_missing.append("minimum_group_n >= 2")
    if "heterogeneity" in required and heterogeneity_validation_mode == "honest_split":
        for value, label in (
            (split_field, "honest split field"),
            (unit_id_field, "unit id field for split-overlap audit"),
        ):
            if not value:
                heterogeneity_missing.append(label)
        if discovery_value in (None, "") or estimation_value in (None, ""):
            heterogeneity_missing.append("distinct discovery and estimation split values")
        elif discovery_value == estimation_value:
            errors.append("heterogeneity_design discovery_value and estimation_value must differ")
            heterogeneity_missing.append("distinct discovery and estimation split values")
        for value, label in (
            (discovery_min_group_n, "discovery_min_group_n >= 2"),
            (estimation_min_group_n, "estimation_min_group_n >= 2"),
            (max_selected_subgroups, "max_selected_subgroups >= 2"),
            (minimum_confirmed_subgroups, "minimum_confirmed_subgroups >= 2"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 2:
                heterogeneity_missing.append(label)
        if (
            isinstance(minimum_confirmed_subgroups, int)
            and not isinstance(minimum_confirmed_subgroups, bool)
            and isinstance(max_selected_subgroups, int)
            and not isinstance(max_selected_subgroups, bool)
            and minimum_confirmed_subgroups > max_selected_subgroups
        ):
            errors.append("heterogeneity_design minimum_confirmed_subgroups cannot exceed max_selected_subgroups")
        if (
            not isinstance(discovery_min_abs_difference, (int, float))
            or isinstance(discovery_min_abs_difference, bool)
            or not math.isfinite(float(discovery_min_abs_difference))
            or float(discovery_min_abs_difference) < 0
        ):
            heterogeneity_missing.append("non-negative discovery_min_abs_difference")
        if selection_metric != "absolute_difference":
            heterogeneity_missing.append("selection_metric: absolute_difference")
        if confirmation_rule != "same_direction_and_interval_excludes_zero":
            heterogeneity_missing.append(
                "confirmation_rule: same_direction_and_interval_excludes_zero"
            )
    if "heterogeneity" in required and effect_scope not in {"descriptive", "causal"}:
        heterogeneity_missing.append("effect_scope: descriptive or causal")
    if effect_scope == "causal" and not heterogeneity_design_refs:
        heterogeneity_missing.append("causal-design evidence for subgroup effects")
    if objective == "estimate_effect" and effect_scope != "causal":
        heterogeneity_missing.append("causal heterogeneity design for effect estimation")
    if not evidence_checked:
        heterogeneity_missing.append("verified segment and comparison evidence")
    if descriptive_status == "blocked":
        heterogeneity_missing.append("usable measured outcome")
        heterogeneity_status = "blocked"
    elif heterogeneity_missing or descriptive_status == "conditional":
        heterogeneity_status = "conditional"
    else:
        heterogeneity_status = "ready"
    layers["heterogeneity"] = _layer(
        heterogeneity_status if "heterogeneity" in required else "not_requested",
        "Average effects can hide opposite subgroup responses; estimate segment-level contrasts and their support.",
        heterogeneity_missing if "heterogeneity" in required else [],
        ["data_lens.deep_analysis_execution"],
    )

    dgp = spec.get("data_generating_process")
    if dgp is None:
        dgp = {}
    if not isinstance(dgp, dict):
        errors.append("data_generating_process must be an object")
        dgp = {}
    observed_drivers = _text_list(
        dgp.get("observed_drivers"), "data_generating_process.observed_drivers", errors
    )
    unobserved_drivers = _text_list(
        dgp.get("unobserved_drivers"), "data_generating_process.unobserved_drivers", errors
    )
    selection_process = _text(dgp.get("selection_process"))
    mechanism_edges = dgp.get("mechanism_edges") or []
    if not isinstance(mechanism_edges, list) or not all(isinstance(item, dict) for item in mechanism_edges):
        errors.append("data_generating_process.mechanism_edges must be an array of objects")
        mechanism_edges = []
    for index, edge in enumerate(mechanism_edges):
        for field in ("source", "target", "relation"):
            if not _text(edge.get(field)):
                errors.append(f"data_generating_process.mechanism_edges[{index}].{field} is required")
        if _text(edge.get("relation")) not in EDGE_RELATIONS:
            errors.append(f"data_generating_process.mechanism_edges[{index}].relation is invalid")
        edge_refs = _text_list(
            edge.get("evidence_refs"),
            f"data_generating_process.mechanism_edges[{index}].evidence_refs",
            errors,
            required=True,
        )
        if evidence_payload is not None:
            unknown_edge_refs = sorted(set(edge_refs) - available_ids)
            if unknown_edge_refs:
                errors.append(
                    f"data_generating_process.mechanism_edges[{index}] has unknown evidence references:"
                    + ",".join(unknown_edge_refs)
                )
            unverified_edge_refs = sorted((set(edge_refs) & available_ids) - verified_ids)
            if unverified_edge_refs:
                errors.append(
                    f"data_generating_process.mechanism_edges[{index}] has unverified evidence references:"
                    + ",".join(unverified_edge_refs)
                )

    mechanisms = spec.get("candidate_mechanisms")
    if mechanisms is None:
        mechanisms = []
    if not isinstance(mechanisms, list) or not all(isinstance(item, dict) for item in mechanisms):
        errors.append("candidate_mechanisms must be an array of objects")
        mechanisms = []
    for index, mechanism in enumerate(mechanisms):
        for field in ("mechanism_id", "claim", "divergent_prediction"):
            if not _text(mechanism.get(field)):
                errors.append(f"candidate_mechanisms[{index}].{field} is required")
    mechanism_design = spec.get("mechanism_design")
    if mechanism_design is None:
        mechanism_design = {}
    if not isinstance(mechanism_design, dict):
        errors.append("mechanism_design must be an object")
        mechanism_design = {}
    mechanism_target = _text(mechanism_design.get("target"))
    mechanism_id = _text(mechanism_design.get("mechanism_id"))
    mechanism_variable = _text(mechanism_design.get("mechanism_variable"))
    changed_variable = _text(mechanism_design.get("changed_or_isolated_variable"))
    baseline_hypothesis_id = _text(mechanism_design.get("baseline_hypothesis_id"))
    candidate_hypothesis_id = _text(mechanism_design.get("candidate_hypothesis_id"))
    mechanism_granularity = _text(mechanism_design.get("required_granularity"))
    mechanism_window = mechanism_design.get("evaluation_window")
    mechanism_measurement = mechanism_design.get("measurement")
    mechanism_predictions = mechanism_design.get("hypothesis_predictions")
    mechanism_missing: list[str] = []
    if not exposure_observed:
        mechanism_missing.append("observed exposure, intervention, or mechanism variable")
    if not temporal_order_known:
        mechanism_missing.append("cause-before-outcome ordering")
    if not mechanisms:
        mechanism_missing.append("at least one mechanism with a divergent prediction")
    for value, label in (
        (mechanism_target, "direct mechanism-test target"),
        (mechanism_id, "mechanism_id selected for direct test"),
        (mechanism_variable, "mechanism variable"),
        (changed_variable, "changed or isolated mechanism variable"),
        (baseline_hypothesis_id, "baseline hypothesis id"),
        (candidate_hypothesis_id, "candidate hypothesis id"),
        (mechanism_granularity, "required mechanism-test granularity"),
    ):
        if "mechanism" in required and not value:
            mechanism_missing.append(label)
    if "mechanism" in required and mechanism_id and mechanism_id not in {
        _text(item.get("mechanism_id")) for item in mechanisms
    }:
        mechanism_missing.append("mechanism_id present in candidate_mechanisms")
    if mechanism_variable and changed_variable and mechanism_variable != changed_variable:
        errors.append("mechanism_design must directly change or isolate mechanism_variable")
        mechanism_missing.append("directly manipulated mechanism variable")
    if baseline_hypothesis_id and candidate_hypothesis_id and baseline_hypothesis_id == candidate_hypothesis_id:
        errors.append("mechanism_design requires distinct baseline and candidate hypotheses")
        mechanism_missing.append("distinct competing hypotheses")
    if "mechanism" in required and not isinstance(mechanism_window, dict):
        mechanism_missing.append("direct-test evaluation window")
    if "mechanism" in required and (
        not isinstance(mechanism_measurement, dict)
        or not _text(mechanism_measurement.get("kind"))
        or not _text(mechanism_measurement.get("field"))
    ):
        mechanism_missing.append("direct-test measurement")
    expected_hypotheses = {baseline_hypothesis_id, candidate_hypothesis_id} - {""}
    if "mechanism" in required and (
        not isinstance(mechanism_predictions, dict)
        or set(mechanism_predictions) != expected_hypotheses
        or len(expected_hypotheses) != 2
        or not all(isinstance(item, dict) for item in (mechanism_predictions or {}).values())
    ):
        mechanism_missing.append("machine-testable predictions for both competing hypotheses")
    if not mechanism_edges:
        mechanism_missing.append("a data-generating-process edge backed by evidence")
    if not selection_process:
        mechanism_missing.append("selection or assignment process")
    if not evidence_checked:
        mechanism_missing.append("verified mechanism and selection evidence")
    if measurement_status == "blocked" or (
        "temporal" in required and temporal_status == "blocked"
    ):
        mechanism_missing.append("usable measured outcome with valid ordering")
        mechanism_status = "blocked"
    elif mechanism_missing or measurement_status == "conditional" or (
        "temporal" in required and temporal_status == "conditional"
    ):
        mechanism_status = "conditional"
    else:
        mechanism_status = "ready"
    layers["mechanism"] = _layer(
        mechanism_status if "mechanism" in required else "not_requested",
        "Mechanisms remain hypotheses until a direct distinguishing test or an eligible causal design supports them.",
        mechanism_missing if "mechanism" in required else [],
        ["data_lens.incremental_discovery", "data_lens.deep_analysis_execution"],
    )

    causal = spec.get("causal_design")
    if causal is None:
        causal = {}
    if not isinstance(causal, dict):
        errors.append("causal_design must be an object")
        causal = {}
    causal_missing: list[str] = []
    causal_design_refs = _text_list(
        causal.get("design_evidence_refs"),
        "causal_design.design_evidence_refs",
        errors,
    )
    if "causal" in required and not causal_design_refs:
        causal_missing.append("verified causal-design evidence")
    if evidence_payload is not None:
        unknown_design_refs = sorted(set(causal_design_refs) - available_ids)
        if unknown_design_refs:
            errors.append(
                "causal_design has unknown design evidence references:"
                + ",".join(unknown_design_refs)
            )
        unverified_design_refs = sorted((set(causal_design_refs) & available_ids) - verified_ids)
        if unverified_design_refs:
            errors.append(
                "causal_design has unverified design evidence references:"
                + ",".join(unverified_design_refs)
            )
        wrong_lane_refs = sorted(
            ref for ref in causal_design_refs
            if ref in evidence_index
            and evidence_index[ref].get("verified") is True
            and evidence_index[ref].get("lane") not in {"experiment_design", "identification_design"}
        )
        if wrong_lane_refs:
            errors.append(
                "causal_design evidence must use experiment_design or identification_design lane:"
                + ",".join(wrong_lane_refs)
            )
    for field, label in (
        ("intervention", "well-defined intervention"),
        ("comparator", "counterfactual comparator"),
        ("group_field", "treatment-group field"),
        ("time_zero", "time zero"),
        ("followup_end", "follow-up end"),
        ("estimand", "target estimand"),
        ("estimator", "planned estimator"),
    ):
        if not _text(causal.get(field)):
            causal_missing.append(label)
    for field, label in (
        ("intervention_value", "intervention group value"),
        ("comparator_value", "comparator group value"),
    ):
        if causal.get(field) in (None, ""):
            causal_missing.append(label)
    assignment = _text(causal.get("assignment_mechanism"))
    identification = _text(causal.get("identification_strategy"))
    estimator = _text(causal.get("estimator"))
    if assignment not in ASSIGNMENT:
        causal_missing.append("assignment mechanism")
    if identification not in IDENTIFICATION or identification == "none":
        causal_missing.append("identification strategy")
    estimator_violation = False
    if identification == "randomized" and estimator not in {
        "group_mean_difference", "group_median_difference", "group_rate_difference"
    }:
        causal_missing.append("randomized estimator compatible with the estimand")
        estimator_violation = True
    if identification == "difference_in_differences" and estimator != "difference_in_differences":
        causal_missing.append("difference_in_differences estimator")
        estimator_violation = True
    positivity = _text(causal.get("positivity"))
    consistency = _text(causal.get("consistency"))
    if positivity not in READINESS:
        causal_missing.append("positivity assessment")
    if consistency not in READINESS:
        causal_missing.append("consistency assessment")
    assumptions = causal.get("assumptions") or []
    if not isinstance(assumptions, list) or not all(isinstance(item, dict) for item in assumptions):
        errors.append("causal_design.assumptions must be an array of objects")
        assumptions = []
    for index, assumption in enumerate(assumptions):
        if not _text(assumption.get("name")):
            errors.append(f"causal_design.assumptions[{index}].name is required")
        if _text(assumption.get("status")) not in {"supported", "untested", "violated"}:
            errors.append(f"causal_design.assumptions[{index}].status is invalid")
        assumption_refs = _text_list(
            assumption.get("evidence_refs"),
            f"causal_design.assumptions[{index}].evidence_refs",
            errors,
        )
        if evidence_payload is not None:
            unknown_assumption_refs = sorted(set(assumption_refs) - available_ids)
            if unknown_assumption_refs:
                errors.append(
                    f"causal_design.assumptions[{index}] has unknown evidence references:"
                    + ",".join(unknown_assumption_refs)
                )
            unverified_assumption_refs = sorted((set(assumption_refs) & available_ids) - verified_ids)
            if unverified_assumption_refs:
                errors.append(
                    f"causal_design.assumptions[{index}] has unverified evidence references:"
                    + ",".join(unverified_assumption_refs)
                )
        if _text(assumption.get("status")) == "supported" and not assumption_refs:
            causal_missing.append(
                "evidence for supported assumption: " + (_text(assumption.get("name")) or str(index))
            )
    confounders = causal.get("known_confounders") or []
    if not isinstance(confounders, list) or not all(isinstance(item, dict) for item in confounders):
        errors.append("causal_design.known_confounders must be an array of objects")
        confounders = []
    for index, confounder in enumerate(confounders):
        if not _text(confounder.get("name")):
            errors.append(f"causal_design.known_confounders[{index}].name is required")
        if _text(confounder.get("status")) not in {"measured", "unmeasured", "unknown"}:
            errors.append(f"causal_design.known_confounders[{index}].status is invalid")
    violated_assumptions = [
        _text(item.get("name")) for item in assumptions if _text(item.get("status")) == "violated"
    ]
    untested_assumptions = [
        _text(item.get("name")) for item in assumptions if _text(item.get("status")) != "supported"
    ]
    unmeasured_confounders = [
        _text(item.get("name")) for item in confounders if _text(item.get("status")) != "measured"
    ]
    design_violation = (
        bool(violated_assumptions)
        or estimator_violation
        or positivity == "violated"
        or consistency == "violated"
        or measurement_status == "blocked"
        or temporal_status == "blocked"
    )
    if measurement_status != "ready":
        causal_missing.append("decision-grade outcome measurement")
    if not exposure_observed:
        causal_missing.append("observed intervention or treatment assignment")
        design_violation = True
    if temporal_status != "ready":
        causal_missing.append("valid temporal ordering and index")
    if assignment == "randomized" and identification not in {"randomized", "none"}:
        causal_missing.append("use randomized identification for randomized assignment")
        design_violation = True
    if assignment in {"observational", "as_if_random"} and identification == "randomized":
        causal_missing.append("identification strategy consistent with non-random assignment")
        design_violation = True
    if assignment in {"observational", "as_if_random"} and not assumptions:
        causal_missing.append("explicit identifying assumptions")
    if not mechanism_edges:
        causal_missing.append("data-generating-process map")
    if not selection_process:
        causal_missing.append("selection or assignment process")
    if assignment == "observational" and _text(causal.get("confounder_review_status")) != "complete":
        causal_missing.append("completed confounder review")
    if assignment in {"observational", "as_if_random", "unknown"} and unmeasured_confounders:
        design_violation = True
        causal_missing.append("measure or bound known confounders: " + ", ".join(filter(None, unmeasured_confounders)))
    if identification == "difference_in_differences" and not (
        repeated_units and pre_post_periods and comparison_groups
    ):
        causal_missing.append("panel or repeated cohorts with pre/post and comparison groups")
        design_violation = True
    if identification == "interrupted_time_series" and not (time_field and pre_post_periods):
        causal_missing.append("time series with explicit pre/post periods")
        design_violation = True

    identification_checks = causal.get("identification_checks") or {}
    if not isinstance(identification_checks, dict):
        errors.append("causal_design.identification_checks must be an object")
        identification_checks = {}

    identification_check_refs: list[str] = []

    def require_check(name: str, label: str) -> None:
        nonlocal design_violation
        raw_check = identification_checks.get(name)
        if not isinstance(raw_check, dict):
            if raw_check is not None:
                errors.append(f"causal_design.identification_checks.{name} must be an object")
            causal_missing.append(label)
            return
        state = _text(raw_check.get("status"))
        refs = _text_list(
            raw_check.get("evidence_refs"),
            f"causal_design.identification_checks.{name}.evidence_refs",
            errors,
        )
        identification_check_refs.extend(refs)
        if state not in READINESS:
            errors.append(f"causal_design.identification_checks.{name}.status is invalid")
        if state != "supported":
            causal_missing.append(label)
        if state == "supported" and not refs:
            causal_missing.append(label + " evidence")
        if evidence_payload is not None:
            unknown_refs = sorted(set(refs) - available_ids)
            unverified_refs = sorted((set(refs) & available_ids) - verified_ids)
            if unknown_refs:
                errors.append(
                    f"causal_design.identification_checks.{name} has unknown evidence references:"
                    + ",".join(unknown_refs)
                )
            if unverified_refs:
                errors.append(
                    f"causal_design.identification_checks.{name} has unverified evidence references:"
                    + ",".join(unverified_refs)
                )
            wrong_lane_refs = sorted(
                ref for ref in refs
                if ref in evidence_index
                and evidence_index[ref].get("verified") is True
                and evidence_index[ref].get("lane") != "identification_check"
            )
            if wrong_lane_refs:
                errors.append(
                    f"causal_design.identification_checks.{name} evidence has invalid lane:"
                    + ",".join(wrong_lane_refs)
                )
            for ref in refs:
                card = evidence_index.get(ref)
                if not card or card.get("verified") is not True:
                    continue
                check_binding = card.get("identification_check_binding")
                if not isinstance(check_binding, dict) or (
                    check_binding.get("check_name") != name
                    or check_binding.get("status") != state
                ):
                    errors.append(
                        f"causal_design.identification_checks.{name} evidence is bound to a different check:"
                        + ref
                    )
        if state == "violated":
            design_violation = True

    if identification == "randomized":
        if not comparison_groups:
            causal_missing.append("observed randomized comparison groups")
            design_violation = True
        require_check("assignment_integrity", "supported random-assignment integrity check")
    elif identification == "backdoor":
        adjustment_set = _text_list(
            identification_checks.get("adjustment_set"),
            "causal_design.identification_checks.adjustment_set",
            errors,
        )
        if not adjustment_set:
            causal_missing.append("declared measured adjustment set")
    elif identification == "difference_in_differences":
        require_check("parallel_trends", "supported pre-treatment parallel-trends check")
        require_check("no_anticipation", "supported no-anticipation check")
    elif identification == "interrupted_time_series":
        if not _text(identification_checks.get("intervention_time")):
            causal_missing.append("explicit intervention time")
        require_check("stable_pretrend", "supported stable pre-intervention trend check")
    elif identification == "regression_discontinuity":
        if not _text(identification_checks.get("running_variable")):
            causal_missing.append("running variable")
        if not _text(identification_checks.get("cutoff")):
            causal_missing.append("assignment cutoff")
        require_check("continuity", "supported continuity/no-manipulation check")
    elif identification == "instrumental_variable":
        if not _text(identification_checks.get("instrument")):
            causal_missing.append("instrument variable")
        require_check("instrument_relevance", "supported instrument relevance check")
        require_check("exclusion_restriction", "supported exclusion-restriction argument")
    elif identification == "frontdoor":
        if not _text(identification_checks.get("mediator")):
            causal_missing.append("observed mediator")
        require_check("frontdoor_criteria", "supported front-door identification criteria")
    if violated_assumptions:
        causal_missing.append("repair violated assumptions: " + ", ".join(filter(None, violated_assumptions)))
    elif untested_assumptions:
        causal_missing.append("support untested assumptions: " + ", ".join(filter(None, untested_assumptions)))
    if not evidence_checked:
        causal_missing.append("verified design and assumption evidence")
    if causal_missing and design_violation:
        causal_status = "blocked"
    elif causal_missing or untested_assumptions or positivity == "uncertain" or consistency == "uncertain":
        causal_status = "conditional"
    else:
        causal_status = "ready"
    layers["causal"] = _layer(
        causal_status if "causal" in required else "not_requested",
        "Identification comes before estimation; an association cannot be promoted by choosing a more complex estimator.",
        causal_missing if "causal" in required else [],
        ["data_lens.deep_data_probes", "data_lens.hypothesis_falsification"],
    )

    prediction = spec.get("prediction_design")
    if prediction is None:
        prediction = {}
    if not isinstance(prediction, dict):
        errors.append("prediction_design must be an object")
        prediction = {}
    predictive_missing = []
    if not _text(prediction.get("metric")):
        predictive_missing.append("out-of-sample error metric")
    baseline_kind = _text(prediction.get("baseline_kind"))
    cutoff_mode = _text(prediction.get("cutoff_mode"))
    if "predictive" in required and baseline_kind not in {
        "last_observation", "seasonal_naive", "median_interval", "custom"
    }:
        predictive_missing.append("structured baseline_kind")
    if "predictive" in required and cutoff_mode not in {"rolling_origin", "fixed_holdout"}:
        predictive_missing.append("structured cutoff_mode")
    prediction_target = _text(prediction.get("target"))
    if "predictive" in required and not prediction_target:
        predictive_missing.append("prediction target")
    horizon_steps = prediction.get("horizon_steps")
    horizon_unit = _text(prediction.get("horizon_unit"))
    if "predictive" in required and (
        not isinstance(horizon_steps, int) or isinstance(horizon_steps, bool) or horizon_steps < 1
    ):
        predictive_missing.append("positive integer forecast horizon_steps")
    if "predictive" in required and not horizon_unit:
        predictive_missing.append("forecast horizon unit")
    canonical_horizon = (
        f"{horizon_steps} {horizon_unit}"
        if isinstance(horizon_steps, int) and not isinstance(horizon_steps, bool)
        and horizon_steps > 0 and horizon_unit else ""
    )
    canonical_baseline = baseline_kind
    canonical_cutoff = (
        "each rolling origin"
        if cutoff_mode == "rolling_origin" else _text(prediction.get("cutoff"))
    )
    validation = _text(prediction.get("validation"))
    model_specs = prediction.get("model_specs") or []
    if not isinstance(model_specs, list) or not all(isinstance(item, dict) for item in model_specs):
        errors.append("prediction_design.model_specs must be an array of objects")
        model_specs = []
    model_ids: list[str] = []
    for index, model in enumerate(model_specs):
        model_id = _text(model.get("model_id"))
        model_kind = _text(model.get("kind"))
        if not model_id or model_id in model_ids:
            errors.append("prediction_design.model_specs model_id values must be present and unique")
        model_ids.append(model_id)
        if model_kind not in PREDICTION_MODEL_KINDS:
            errors.append(f"prediction_design.model_specs[{index}].kind is invalid")
        if model_kind == "rolling_mean" and (
            not isinstance(model.get("window"), int)
            or isinstance(model.get("window"), bool)
            or model.get("window") < 2
        ):
            errors.append(f"prediction_design.model_specs[{index}].window must be >= 2")
        if model_kind == "seasonal_naive" and (
            not isinstance(model.get("season_length"), int)
            or isinstance(model.get("season_length"), bool)
            or model.get("season_length") < 2
        ):
            errors.append(f"prediction_design.model_specs[{index}].season_length must be >= 2")
    baseline_model_id = _text(prediction.get("baseline_model_id"))
    minimum_history = prediction.get("minimum_history")
    minimum_improvement = prediction.get("minimum_improvement")
    uncertainty_method = _text(prediction.get("uncertainty_method"))
    confidence_level = prediction.get("confidence_level")
    bootstrap_replicates = prediction.get("bootstrap_replicates")
    bootstrap_seed = prediction.get("bootstrap_seed")
    block_length = prediction.get("block_length")
    minimum_origins = prediction.get("minimum_origins")
    if "predictive" in required and len(model_specs) < 2:
        predictive_missing.append("baseline plus at least one forecast competitor")
    if "predictive" in required and baseline_model_id not in model_ids:
        predictive_missing.append("baseline_model_id present in model_specs")
    if "predictive" in required and (
        not isinstance(minimum_history, int)
        or isinstance(minimum_history, bool)
        or minimum_history < 2
    ):
        predictive_missing.append("minimum_history >= 2")
    if "predictive" in required and (
        not isinstance(minimum_improvement, (int, float))
        or isinstance(minimum_improvement, bool)
        or not math.isfinite(float(minimum_improvement))
        or not 0 <= float(minimum_improvement) <= 1
    ):
        predictive_missing.append("minimum_improvement between 0 and 1")
    if "predictive" in required and _text(prediction.get("metric")).lower() not in {"mae", "rmse"}:
        predictive_missing.append("supported forecast metric: MAE or RMSE")
    if "predictive" in required and uncertainty_method != "circular_block_bootstrap":
        predictive_missing.append("circular-block uncertainty for paired forecast losses")
    if "predictive" in required and (
        not isinstance(confidence_level, (int, float))
        or isinstance(confidence_level, bool)
        or not math.isfinite(float(confidence_level))
        or not 0 < float(confidence_level) < 1
    ):
        predictive_missing.append("confidence_level between 0 and 1")
    if "predictive" in required and (
        not isinstance(bootstrap_replicates, int)
        or isinstance(bootstrap_replicates, bool)
        or bootstrap_replicates < 200
    ):
        predictive_missing.append("bootstrap_replicates >= 200")
    if "predictive" in required and (
        not isinstance(bootstrap_seed, int) or isinstance(bootstrap_seed, bool)
    ):
        predictive_missing.append("fixed integer bootstrap_seed")
    if "predictive" in required and (
        not isinstance(block_length, int)
        or isinstance(block_length, bool)
        or block_length < 1
        or (
            isinstance(horizon_steps, int)
            and not isinstance(horizon_steps, bool)
            and block_length < horizon_steps
        )
    ):
        predictive_missing.append("block_length >= horizon_steps")
    if "predictive" in required and (
        not isinstance(minimum_origins, int)
        or isinstance(minimum_origins, bool)
        or minimum_origins < 5
    ):
        predictive_missing.append("minimum_origins >= 5")
    if "predictive" in required and validation != "rolling_origin":
        predictive_missing.append("implemented rolling-origin model competition")
    if "predictive" in required and cutoff_mode == "fixed_holdout" and not canonical_cutoff:
        predictive_missing.append("fixed training cutoff")
    if not evidence_checked:
        predictive_missing.append("verified training and evaluation evidence")
    allowed_validation = TIME_SAFE_VALIDATION if time_field else CROSS_SECTION_SAFE_VALIDATION
    leakage = bool(validation and validation not in allowed_validation)
    if validation not in allowed_validation:
        predictive_missing.append(
            "rolling-origin or future-holdout validation" if time_field else "independent holdout validation"
        )
    validation_mode_mismatch = (
        validation == "rolling_origin" and cutoff_mode != "rolling_origin"
    ) or (
        validation in {"future_holdout", "independent_holdout"}
        and cutoff_mode != "fixed_holdout"
    )
    if validation_mode_mismatch:
        errors.append("prediction validation and cutoff_mode are inconsistent")
        predictive_missing.append("cutoff mode consistent with validation")
        leakage = True
    if measurement_status == "blocked" or (time_field and temporal_status == "blocked"):
        predictive_status = "blocked"
        predictive_missing.append("usable measured outcome with valid ordering")
    elif leakage:
        predictive_status = "blocked"
        warnings.append("time-dependent prediction cannot use random_split or in-sample accuracy")
    elif predictive_missing or measurement_status == "conditional" or (
        time_field and temporal_status == "conditional"
    ):
        predictive_status = "conditional"
    else:
        predictive_status = "ready"
    layers["predictive"] = _layer(
        predictive_status if "predictive" in required else "not_requested",
        "Prediction is evaluated on observations unavailable at fitting time and is not evidence of a causal explanation.",
        predictive_missing if "predictive" in required else [],
        ["data_lens.deep_analysis_execution"],
    )

    decision = spec.get("decision_design")
    if decision is None:
        decision = {}
    if not isinstance(decision, dict):
        errors.append("decision_design must be an object")
        decision = {}
    decision_missing = [
        label
        for field, label in (
            ("actor", "decision owner"),
            ("utility_metric", "utility or value metric"),
            ("decision_threshold", "decision threshold"),
        )
        if not _text(decision.get(field))
    ]
    decision_target = _text(decision.get("target"))
    if "decision" in required and not decision_target:
        decision_missing.append("decision target")
    action_options = _text_list(decision.get("action_options"), "decision_design.action_options", errors)
    costs = _text_list(decision.get("costs"), "decision_design.costs", errors)
    constraints = _text_list(decision.get("constraints"), "decision_design.constraints", errors)
    evaluation_mode = _text(decision.get("evaluation_mode")) or "scenario_utility"
    action_field = _text(decision.get("action_field"))
    benefit_field = _text(decision.get("benefit_field"))
    cost_field = _text(decision.get("cost_field"))
    probability_field = _text(decision.get("probability_field"))
    weight_field = _text(decision.get("weight_field"))
    baseline_action = _text(decision.get("baseline_action"))
    fallback_action = _text(decision.get("fallback_action"))
    withdrawal_condition = _text(decision.get("withdrawal_condition"))
    minimum_net_utility = decision.get("minimum_net_utility")
    minimum_advantage = decision.get("minimum_advantage")
    logged_action_field = _text(decision.get("logged_action_field"))
    action_values = _text_list(decision.get("action_values"), "decision_design.action_values", errors)
    reward_field = _text(decision.get("reward_field"))
    propensity_field = _text(decision.get("propensity_field"))
    bootstrap_unit_field = _text(decision.get("bootstrap_unit_field"))
    estimators = _text_list(decision.get("estimators"), "decision_design.estimators", errors)
    primary_estimator = _text(decision.get("primary_estimator"))
    q_logged_field = _text(decision.get("q_logged_field"))
    policy_specs = decision.get("policy_specs") or []
    minimum_effective_sample_size = decision.get("minimum_effective_sample_size")
    maximum_importance_weight = decision.get("maximum_importance_weight")
    decision_confidence_level = decision.get("confidence_level")
    decision_bootstrap_replicates = decision.get("bootstrap_replicates")
    decision_bootstrap_seed = decision.get("bootstrap_seed")
    weight_clip_grid = decision.get("weight_clip_grid") or []
    propensity_floor_grid = decision.get("propensity_floor_grid") or []
    constraint_rules = decision.get("constraint_rules") or []
    if not isinstance(constraint_rules, list) or not all(isinstance(item, dict) for item in constraint_rules):
        errors.append("decision_design.constraint_rules must be an array of objects")
        constraint_rules = []
    for index, rule in enumerate(constraint_rules):
        if not _text(rule.get("field")):
            errors.append(f"decision_design.constraint_rules[{index}].field is required")
        if _text(rule.get("aggregation")) not in DECISION_CONSTRAINT_AGGREGATIONS:
            errors.append(f"decision_design.constraint_rules[{index}].aggregation is invalid")
        if not _text(rule.get("operator")) or rule.get("value") is None:
            errors.append(f"decision_design.constraint_rules[{index}] requires operator and value")
    for value, label in (
        (baseline_action, "baseline action"),
        (fallback_action, "fallback action"),
        (withdrawal_condition, "withdrawal condition"),
    ):
        if "decision" in required and not value:
            decision_missing.append(label)
    if "decision" in required and baseline_action not in action_options:
        decision_missing.append("baseline action present in action_options")
    if "decision" in required and fallback_action not in action_options:
        decision_missing.append("fallback action present in action_options")
    decision_threshold_values = [
        (minimum_advantage, "numeric minimum advantage over baseline"),
    ]
    if evaluation_mode == "scenario_utility":
        decision_threshold_values.append(
            (minimum_net_utility, "numeric minimum net utility")
        )
    for value, label in decision_threshold_values:
        if "decision" in required and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            decision_missing.append(label)
    if evaluation_mode not in {"scenario_utility", "logged_policy"}:
        errors.append("decision_design.evaluation_mode is invalid")
    if "decision" in required and evaluation_mode == "scenario_utility":
        for value, label in (
            (action_field, "action field"),
            (benefit_field, "benefit field"),
            (cost_field, "cost field"),
        ):
            if not value:
                decision_missing.append(label)
    if "decision" in required and evaluation_mode == "logged_policy":
        for value, label in (
            (logged_action_field, "logged action field"),
            (reward_field, "observed reward field"),
            (propensity_field, "logging propensity field"),
            (bootstrap_unit_field, "independent bootstrap unit field"),
        ):
            if not value:
                decision_missing.append(label)
        if reward_field and reward_field != _text(outcome.get("field")):
            errors.append("decision_design.reward_field must match scope.outcome.field")
            decision_missing.append("reward field bound to the declared outcome")
        if len(action_values) < 2:
            decision_missing.append("at least two logged action values")
        if not isinstance(policy_specs, list) or len(policy_specs) < 2 or not all(
            isinstance(item, dict) for item in policy_specs
        ):
            decision_missing.append("at least two structured offline policies")
            policy_specs = []
        policy_ids: list[str] = []
        for index, policy in enumerate(policy_specs):
            policy_id = _text(policy.get("policy_id"))
            if not policy_id or policy_id in policy_ids:
                errors.append("decision_design.policy_specs policy_id values must be present and unique")
            policy_ids.append(policy_id)
            policy_type = _text(policy.get("policy_type"))
            if policy_type not in {
                "explicit_probabilities", "logging_policy", "uniform_policy",
            }:
                errors.append(f"decision_design.policy_specs[{index}].policy_type is invalid")
            probability_fields = policy.get("action_probability_fields")
            if policy_type == "explicit_probabilities" and (
                not isinstance(probability_fields, dict)
                or set(probability_fields) != set(action_values)
                or not all(_text(value) for value in (probability_fields or {}).values())
            ):
                errors.append(
                    f"decision_design.policy_specs[{index}].action_probability_fields must bind every action value"
                )
            if policy_type != "explicit_probabilities" and probability_fields not in (None, {}):
                errors.append(
                    f"decision_design.policy_specs[{index}].action_probability_fields is only valid for explicit_probabilities"
                )
            if "doubly_robust" in estimators and not _text(policy.get("q_policy_field")):
                decision_missing.append(
                    f"q_policy_field for policy {policy_id or index}"
                )
        if set(policy_ids) != set(action_options):
            decision_missing.append("action_options equal the offline policy ids")
        if not estimators or any(
            estimator not in {"ips", "snips", "doubly_robust"}
            for estimator in estimators
        ):
            decision_missing.append("supported offline estimators")
        if primary_estimator not in estimators:
            decision_missing.append("primary_estimator present in estimators")
        if "doubly_robust" in estimators and not q_logged_field:
            decision_missing.append("q_logged_field for doubly robust estimation")
        for value, label in (
            (minimum_effective_sample_size, "positive minimum effective sample size"),
            (maximum_importance_weight, "positive maximum importance weight"),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                decision_missing.append(label)
        if (
            not isinstance(decision_confidence_level, (int, float))
            or isinstance(decision_confidence_level, bool)
            or not math.isfinite(float(decision_confidence_level))
            or not 0 < float(decision_confidence_level) < 1
        ):
            decision_missing.append("confidence_level between 0 and 1")
        if (
            not isinstance(decision_bootstrap_replicates, int)
            or isinstance(decision_bootstrap_replicates, bool)
            or decision_bootstrap_replicates < 200
        ):
            decision_missing.append("bootstrap_replicates >= 200")
        if not isinstance(decision_bootstrap_seed, int) or isinstance(decision_bootstrap_seed, bool):
            decision_missing.append("fixed integer bootstrap_seed")
        for values, label, upper in (
            (weight_clip_grid, "positive weight_clip_grid", None),
            (propensity_floor_grid, "propensity_floor_grid values between 0 and 1", 1),
        ):
            if (
                not isinstance(values, list)
                or not values
                or len(values) != len(set(values))
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) <= 0
                    or (upper is not None and float(value) >= upper)
                    for value in values
                )
            ):
                decision_missing.append(label)
    if len(action_options) < 2:
        decision_missing.append("at least two action options")
    if not costs:
        decision_missing.append("action costs or downside")
    if not constraints:
        decision_missing.append("operating constraints")
    if decision_basis not in DECISION_BASES:
        decision_missing.append("decision evidence basis: causal_effect, prediction, or descriptive_rule")
        basis_status = "conditional"
    elif decision_basis == "causal_effect":
        basis_status = causal_status
    elif decision_basis == "prediction":
        basis_status = predictive_status
    else:
        basis_status = descriptive_status
    if basis_status == "blocked" or (
        "heterogeneity" in required and heterogeneity_status == "blocked"
    ):
        decision_status = "blocked"
        decision_missing.append(f"a usable {decision_basis or 'declared'} input")
    elif decision_missing or basis_status == "conditional" or (
        "heterogeneity" in required and heterogeneity_status == "conditional"
    ):
        decision_status = "conditional"
    else:
        decision_status = "ready"
    layers["decision"] = _layer(
        decision_status if "decision" in required else "not_requested",
        "An estimate becomes decision support only after value, cost, constraints, threshold, and fallback are explicit.",
        decision_missing if "decision" in required else [],
        ["data_lens.deep_analysis_execution"],
    )

    for name in LAYER_ORDER:
        if name not in required:
            layers[name]["status"] = "not_requested"
            layers[name]["missing_requirements"] = []

    expected_design_binding = {
        "analysis_unit": analysis_unit,
        "outcome_name": _text(outcome.get("name")),
        "outcome_field": _text(outcome.get("field")),
        "intervention": _text(causal.get("intervention")),
        "comparator": _text(causal.get("comparator")),
        "group_field": _text(causal.get("group_field")),
        "intervention_value": causal.get("intervention_value"),
        "comparator_value": causal.get("comparator_value"),
        "assignment_mechanism": assignment,
        "identification_strategy": identification,
        "estimand": _text(causal.get("estimand")),
        "estimator": estimator,
    }
    if evidence_payload is not None and "causal" in required:
        for ref in dict.fromkeys(causal_design_refs + identification_check_refs):
            card = evidence_index.get(ref)
            if not card or card.get("verified") is not True:
                continue
            actual_binding = card.get("design_binding")
            if actual_binding != expected_design_binding:
                errors.append(
                    "causal-design evidence is not bound to the compiled analysis question:"
                    + ref
                )
                causal_missing.append("design evidence bound to the declared causal target")
                causal_status = "blocked"
                layers["causal"] = _layer(
                    "blocked",
                    "Identification comes before estimation; design evidence must name the same unit, outcome, intervention, comparator, and estimand.",
                    causal_missing,
                    ["data_lens.deep_data_probes", "data_lens.hypothesis_falsification"],
                )

    claim_permissions = {
        "descriptive": "allowed" if descriptive_status == "ready" else descriptive_status,
        "association": "allowed" if descriptive_status == "ready" and exposure_observed else (
            descriptive_status if exposure_observed else "blocked"
        ),
        "mechanism_hypothesis": "allowed" if mechanism_status == "ready" else mechanism_status,
        "predictive": "allowed" if predictive_status == "ready" and "predictive" in required else (
            predictive_status if "predictive" in required else "not_requested"
        ),
        "causal": "allowed" if causal_status == "ready" and "causal" in required else (
            causal_status if "causal" in required else "not_requested"
        ),
        "decision": "allowed" if decision_status == "ready" and "decision" in required else (
            decision_status if "decision" in required else "not_requested"
        ),
    }

    probes: list[dict[str, str]] = []
    if "temporal" in required:
        probes.append({"probe": "change_point_candidate", "purpose": "locate stage shifts without assigning a cause"})
    if "heterogeneity" in required:
        probes.append({
            "probe": (
                "honest_subgroup_mean_difference"
                if heterogeneity_validation_mode == "honest_split"
                else "subgroup_mean_difference_spread"
            ),
            "purpose": (
                "select subgroup candidates in the discovery sample and test the frozen candidates on non-overlapping estimation units"
                if heterogeneity_validation_mode == "honest_split"
                else "execute plan-bound prespecified subgroup contrasts and detect whether averages hide opposite responses"
            ),
        })
    if "mechanism" in required:
        probes.append({"probe": "direct_mechanism_test", "purpose": "change or isolate the declared mechanism variable and distinguish frozen E0/E1 predictions"})
    if identification == "difference_in_differences":
        probes.append({"probe": "difference_in_differences", "purpose": "estimate the treated-minus-control pre/post contrast under declared assumptions"})
    if "predictive" in required:
        probes.append({"probe": "rolling_origin_model_competition", "purpose": "compare the baseline and forecast competitors on identical future-safe origins and require a paired circular-block loss interval before declaring a win"})
    if "decision" in required:
        probes.append({
            "probe": (
                "offline_policy_value_sensitivity"
                if evaluation_mode == "logged_policy"
                else "expected_net_utility"
            ),
            "purpose": (
                "estimate logged-policy value with propensity correction, overlap diagnostics, uncertainty, and clipping/floor sensitivity"
                if evaluation_mode == "logged_policy"
                else "compare feasible actions under frozen benefit, cost, threshold, and fallback rules"
            ),
        })

    blocked_layers = [name for name in LAYER_ORDER if layers[name]["status"] == "blocked"]
    conditional_layers = [name for name in LAYER_ORDER if layers[name]["status"] == "conditional"]
    heterogeneity_target_binding = {
        "target": heterogeneity_target,
        "analysis_unit": analysis_unit,
        "outcome_field": _text(outcome.get("field")),
        "segment_field": segment_field,
        "group_field": heterogeneity_group_field,
        "group_a": heterogeneity_group_a,
        "group_b": heterogeneity_group_b,
        "effect_scope": effect_scope,
        "design_evidence_refs": heterogeneity_design_refs,
        "planned_method": (
            "honest_subgroup_mean_difference"
            if heterogeneity_validation_mode == "honest_split"
            else "subgroup_mean_difference_spread"
        ),
        "validation_type": "subgroup_analysis",
    }
    if heterogeneity_validation_mode == "honest_split":
        heterogeneity_target_binding.update({
            "validation_mode": heterogeneity_validation_mode,
            "split_field": split_field,
            "discovery_value": discovery_value,
            "estimation_value": estimation_value,
            "unit_id_field": unit_id_field,
            "discovery_min_group_n": discovery_min_group_n,
            "estimation_min_group_n": estimation_min_group_n,
            "discovery_min_abs_difference": discovery_min_abs_difference,
            "max_selected_subgroups": max_selected_subgroups,
            "minimum_confirmed_subgroups": minimum_confirmed_subgroups,
            "selection_metric": selection_metric,
            "confirmation_rule": confirmation_rule,
        })
    else:
        heterogeneity_target_binding["minimum_group_n"] = minimum_group_n

    decision_target_binding = {
        "target": decision_target,
        "evidence_basis": decision_basis,
        "actor": _text(decision.get("actor")),
        "utility_metric": _text(decision.get("utility_metric")),
        "decision_threshold": _text(decision.get("decision_threshold")),
        "analysis_unit": analysis_unit,
        "outcome_field": _text(outcome.get("field")),
        "action_options": action_options,
        "baseline_action": baseline_action,
        "fallback_action": fallback_action,
        "minimum_advantage": minimum_advantage,
        "withdrawal_condition": withdrawal_condition,
        "validation_type": "policy_evaluation",
    }
    if evaluation_mode == "logged_policy":
        decision_target_binding.update({
            "evaluation_mode": evaluation_mode,
            "logged_action_field": logged_action_field,
            "action_values": action_values,
            "reward_field": reward_field,
            "propensity_field": propensity_field,
            "bootstrap_unit_field": bootstrap_unit_field,
            "estimators": estimators,
            "primary_estimator": primary_estimator,
            "policy_specs": copy.deepcopy(policy_specs),
            "minimum_effective_sample_size": minimum_effective_sample_size,
            "maximum_importance_weight": maximum_importance_weight,
            "confidence_level": decision_confidence_level,
            "bootstrap_replicates": decision_bootstrap_replicates,
            "bootstrap_seed": decision_bootstrap_seed,
            "weight_clip_grid": copy.deepcopy(weight_clip_grid),
            "propensity_floor_grid": copy.deepcopy(propensity_floor_grid),
            "planned_method": "offline_policy_value_sensitivity",
        })
        if "doubly_robust" in estimators:
            decision_target_binding["q_logged_field"] = q_logged_field
    else:
        decision_target_binding.update({
            "evaluation_mode": "scenario_utility",
            "action_field": action_field,
            "benefit_field": benefit_field,
            "cost_field": cost_field,
            "probability_field": probability_field,
            "weight_field": weight_field,
            "minimum_net_utility": minimum_net_utility,
            "constraint_rules": copy.deepcopy(constraint_rules),
            "planned_method": "expected_net_utility",
        })
    return {
        "contract_version": RESULT_VERSION,
        "source_question_spec": copy.deepcopy(spec),
        "decision_question": decision_question,
        "objective": objective,
        "analysis_unit": analysis_unit,
        "population": population,
        "data_generating_process": {
            "observed_drivers": observed_drivers,
            "unobserved_drivers": unobserved_drivers,
            "selection_process": selection_process,
            "mechanism_edge_count": len(mechanism_edges),
        },
        "analysis_targets": {
            "data_evidence_refs": evidence_refs,
            "outcome": {
                "name": _text(outcome.get("name")),
                "field": _text(outcome.get("field")),
                "unit": _text(outcome.get("unit")),
            },
            "time": {"field": time_field, "granularity": time_granularity},
            "heterogeneity": heterogeneity_target_binding,
            "mechanism": {
                "target": mechanism_target,
                "analysis_unit": analysis_unit,
                "outcome_field": _text(mechanism_measurement.get("field")) if isinstance(mechanism_measurement, dict) else "",
                "mechanism_id": mechanism_id,
                "mechanism_variable": mechanism_variable,
                "changed_or_isolated_variable": changed_variable,
                "baseline_hypothesis_id": baseline_hypothesis_id,
                "candidate_hypothesis_id": candidate_hypothesis_id,
                "required_granularity": mechanism_granularity,
                "evaluation_window": copy.deepcopy(mechanism_window),
                "measurement": copy.deepcopy(mechanism_measurement),
                "hypothesis_predictions": copy.deepcopy(mechanism_predictions),
                "planned_method": _text(mechanism_measurement.get("kind")) if isinstance(mechanism_measurement, dict) else "",
                "validation_type": "direct_mechanism_test",
            },
            "predictive": {
                "target": prediction_target,
                "analysis_unit": analysis_unit,
                "outcome_field": _text(outcome.get("field")),
                "time_field": time_field,
                "horizon": canonical_horizon,
                "horizon_steps": horizon_steps,
                "horizon_unit": horizon_unit,
                "cutoff": canonical_cutoff,
                "cutoff_mode": cutoff_mode,
                "validation": validation,
                "metric": _text(prediction.get("metric")),
                "baseline_model": canonical_baseline,
                "baseline_kind": baseline_kind,
                "baseline_model_id": baseline_model_id,
                "minimum_history": minimum_history,
                "minimum_improvement": minimum_improvement,
                "model_specs": copy.deepcopy(model_specs),
                "uncertainty_method": uncertainty_method,
                "confidence_level": confidence_level,
                "bootstrap_replicates": bootstrap_replicates,
                "bootstrap_seed": bootstrap_seed,
                "block_length": block_length,
                "minimum_origins": minimum_origins,
                "planned_method": "rolling_origin_model_competition",
                "validation_type": "out_of_sample",
            },
            "causal": {
                "target": _text(causal.get("estimand")),
                "intervention": _text(causal.get("intervention")),
                "comparator": _text(causal.get("comparator")),
                "outcome_field": _text(outcome.get("field")),
                "group_field": _text(causal.get("group_field")),
                "intervention_value": causal.get("intervention_value"),
                "comparator_value": causal.get("comparator_value"),
                "identification_strategy": identification,
                "planned_method": estimator,
                "design_evidence_refs": list(dict.fromkeys(causal_design_refs + identification_check_refs)),
            },
            "decision": decision_target_binding,
        },
        "contract_status": "invalid" if errors else "compiled",
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "analysis_layers": layers,
        "claim_permissions": claim_permissions,
        "recommended_probes": probes,
        "summary": {
            "required_layers": [name for name in LAYER_ORDER if name in required],
            "blocked_layers": blocked_layers,
            "conditional_layers": conditional_layers,
            "overall_depth_label": None,
            "note": "No overall depth score is emitted; each analytical capability keeps its own readiness and claim boundary.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a decision question into independent measurement, temporal, heterogeneity, mechanism, causal, predictive, and decision-analysis layers."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.spec, *([args.evidence_cards] if args.evidence_cards else [])]
    guard_cli_output(parser, args.output, inputs)
    evidence = load_json(args.evidence_cards) if args.evidence_cards else None
    result = compile_deep_analysis_question(
        load_json(args.spec),
        evidence,
        args.evidence_cards.resolve().parent if args.evidence_cards else None,
    )
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "contract_status": result["contract_status"]}, ensure_ascii=False))
    return 0 if result["contract_status"] == "compiled" else 2


if __name__ == "__main__":
    raise SystemExit(main())
