from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from _common import (
    file_sha256,
    guard_cli_output,
    has_explicit_action_directive,
    has_explicit_causal_wording,
    has_explicit_prediction_wording,
    has_hypothesis_qualifier,
    has_noncausal_relation_wording,
    load_json,
    write_json,
)


VERIFIED_STATUSES = {
    "verified",
    "verified_local",
    "derived_verified",
    "bounded_verified",
    "formula_verified",
    "source_stated",
    "source_stated_directional",
}
CLAIM_LEVELS = {
    "fact",
    "calculation",
    "pattern",
    "relationship",
    "mechanism_hypothesis",
    "prediction",
    "causal_effect",
    "decision_rule",
}
INFERENCE_LEVELS = {
    "pattern",
    "relationship",
    "mechanism_hypothesis",
    "prediction",
    "causal_effect",
    "decision_rule",
}
CLAIM_PERMISSION = {
    "fact": "descriptive",
    "calculation": "descriptive",
    "pattern": "descriptive",
    "relationship": "association",
    "mechanism_hypothesis": "mechanism_hypothesis",
    "prediction": "predictive",
    "causal_effect": "causal",
    "decision_rule": "decision",
}
ADVANCED_CLAIM_LEVELS = {"prediction", "causal_effect", "decision_rule"}
SUBSTANTIVE_RESULT_LAYERS = {"heterogeneity", "mechanism", "causal", "predictive", "decision"}
ADVANCED_VALIDATION_TYPES = {
    "prediction": {"out_of_sample"},
    "causal_effect": {"randomized_experiment", "identified_observational_estimate"},
    "decision_rule": {"decision_analysis", "policy_evaluation"},
}
LEGACY_RESULT_CONTRACT = "data-lens-hypothesis-experiment-result/0.2"
DEEP_EXECUTION_RESULT_CONTRACTS = {
    "data-lens-deep-analysis-execution-result/0.1",
    "data-lens-deep-analysis-execution-result/0.2",
}
TRUSTED_RESULT_CONTRACTS = {LEGACY_RESULT_CONTRACT, *DEEP_EXECUTION_RESULT_CONTRACTS}
RESULT_LAYER_VALIDATIONS = {
    "heterogeneity": {"subgroup_analysis"},
    "mechanism": {"direct_mechanism_test"},
    "predictive": {"out_of_sample"},
    "causal": {"randomized_experiment", "identified_observational_estimate"},
    "decision": {"decision_analysis", "policy_evaluation"},
}
DESIGN_LANES = {"experiment_design", "identification_design", "identification_check"}
PLAN_INTEGRITY_FIELDS = (
    "contract_version",
    "contract_status",
    "decision_question",
    "objective",
    "analysis_unit",
    "population",
    "data_generating_process",
    "analysis_targets",
    "analysis_layers",
    "claim_permissions",
    "recommended_probes",
    "summary",
)
COUNTER_STATUSES = {"completed_none_found", "completed_with_counterexamples", "not_completed"}
ROBUSTNESS_STATUSES = {"passed", "mixed", "failed", "not_applicable"}
ALTERNATIVE_STATUSES = {"supported", "less_supported", "unresolved", "rejected"}
ADOPT_VALUES = {"adopt", "adopted", "proposed_adopted"}
REJECT_VALUES = {"reject", "rejected", "proposed_rejected"}


def _request(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    value = payload.get("request")
    if not isinstance(value, dict):
        return {"attempted": False, "succeeded": False, "provider": None, "request_count": 0}, ["request must be an object"]
    errors: list[str] = []
    attempted = value.get("attempted")
    succeeded = value.get("succeeded")
    count = value.get("request_count")
    if not isinstance(attempted, bool) or not isinstance(succeeded, bool):
        errors.append("request.attempted and request.succeeded must be boolean")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append("request.request_count must be a non-negative integer")
        count = 0
    if succeeded is True and (attempted is not True or count < 1):
        errors.append("a successful request requires attempted=true and request_count>=1")
    if attempted is False and count != 0:
        errors.append("an unattempted request requires request_count=0")
    return {
        "attempted": attempted if isinstance(attempted, bool) else False,
        "succeeded": succeeded if isinstance(succeeded, bool) else False,
        "provider": value.get("provider"),
        "request_count": count,
    }, errors


def _json_pointer(document: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return document
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def _verify_locator(
    path: Path,
    locator: Any,
    content_cache: dict[tuple[str, Path], Any] | None = None,
) -> list[str]:
    if not isinstance(locator, dict):
        return ["locator_missing"]
    kind = locator.get("type")
    try:
        if kind == "json_pointer":
            key = ("json", path)
            document = content_cache.get(key) if content_cache is not None else None
            if document is None:
                document = load_json(path)
                if content_cache is not None:
                    content_cache[key] = document
            actual = _json_pointer(document, str(locator.get("pointer") or ""))
            if "expected" in locator and actual != locator["expected"]:
                return ["locator_expected_mismatch"]
        elif kind == "line_range":
            key = ("lines", path)
            lines = content_cache.get(key) if content_cache is not None else None
            if lines is None:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
                if content_cache is not None:
                    content_cache[key] = lines
            start, end = int(locator["start"]), int(locator["end"])
            if start < 1 or end < start or end > len(lines):
                return ["locator_line_range_invalid"]
            quote = str(locator.get("quote") or "").strip()
            if quote and re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", "\n".join(lines[start - 1:end])):
                return ["locator_quote_mismatch"]
        elif kind == "csv_row":
            key = ("csv", path)
            rows = content_cache.get(key) if content_cache is not None else None
            if rows is None:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                if content_cache is not None:
                    content_cache[key] = rows
            row_number = int(locator["row"])
            if row_number < 1 or row_number > len(rows):
                return ["locator_csv_row_invalid"]
        elif kind in {"text_span", "image", "pdf_pages", "video_frames"}:
            if not locator:
                return ["locator_empty"]
        else:
            return ["locator_type_invalid"]
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return ["locator_unresolvable"]
    return []


def _canonical_result_claim(target: Any, method: Any, measurement: Any) -> str:
    value = measurement.get("value") if isinstance(measurement, dict) else None
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{str(target or '').strip()}：{str(method or '').strip()} 的测量值为 {rendered}。"


def _advanced_presentation(claim: str) -> dict[str, str]:
    return {
        "title": claim,
        "decision_relevance": "该结果只回答已编译的分析目标，并按其证据层级进入决策。",
        "baseline": "以编译后的分析目标、实际测量和设计边界为准。",
        "decision_delta": "只在冻结的目标、方法、验证设计与失效条件内使用；超出边界须重新评估。",
    }


def _binding_plan_mismatches(
    binding: dict[str, Any], layer: str, plan_targets: dict[str, Any]
) -> list[str]:
    """Return semantic fields that do not match the freshly compiled target."""
    target = plan_targets.get(layer)
    if not isinstance(target, dict):
        return ["analysis_target"]
    mapping: list[tuple[str, str]] = [
        ("target", "target"),
        ("outcome_field", "outcome_field"),
        ("method", "planned_method"),
    ]
    if layer in {"heterogeneity", "mechanism", "decision"}:
        mapping.append(("analysis_unit", "analysis_unit"))
        mapping.append(("validation_type", "validation_type"))
    elif layer == "predictive":
        mapping.extend([
            ("analysis_unit", "analysis_unit"),
            ("validation_type", "validation_type"),
            ("validation_design", "validation"),
            ("time_field", "time_field"),
        ])
    elif layer == "causal":
        expected_validation = (
            "randomized_experiment"
            if target.get("identification_strategy") == "randomized"
            else "identified_observational_estimate"
        )
        if binding.get("validation_type") != expected_validation:
            mapping.append(("validation_type", "__expected_validation__"))
            target = {**target, "__expected_validation__": expected_validation}

    layer_fields = {
        "heterogeneity": (
            "segment_field", "group_field", "group_a", "group_b",
            "minimum_group_n", "effect_scope", "design_evidence_refs",
        ),
        "mechanism": (
            "mechanism_id", "mechanism_variable", "changed_or_isolated_variable",
            "baseline_hypothesis_id", "candidate_hypothesis_id",
            "required_granularity", "evaluation_window", "measurement",
            "hypothesis_predictions",
        ),
        "predictive": (
            "horizon", "horizon_steps", "horizon_unit", "cutoff", "cutoff_mode",
            "metric", "baseline_model", "baseline_kind", "baseline_model_id",
            "minimum_history", "minimum_improvement", "model_specs",
            "uncertainty_method", "confidence_level", "bootstrap_replicates",
            "bootstrap_seed", "block_length", "minimum_origins",
        ),
        "causal": (
            "intervention", "comparator", "group_field", "intervention_value",
            "comparator_value", "identification_strategy", "design_evidence_refs",
        ),
        "decision": (
            "evidence_basis", "utility_metric", "decision_threshold", "action_field",
            "action_options", "benefit_field", "cost_field", "probability_field",
            "weight_field", "baseline_action", "fallback_action",
            "minimum_net_utility", "minimum_advantage", "constraint_rules",
            "withdrawal_condition",
        ),
    }
    mapping.extend((field, field) for field in layer_fields.get(layer, ()))
    if layer == "heterogeneity" and target.get("planned_method") == "honest_subgroup_mean_difference":
        mapping.extend((field, field) for field in (
            "validation_mode", "split_field", "discovery_value", "estimation_value",
            "unit_id_field", "discovery_min_group_n", "estimation_min_group_n",
            "discovery_min_abs_difference", "max_selected_subgroups",
            "minimum_confirmed_subgroups", "selection_metric", "confirmation_rule",
        ))
    if layer == "decision" and target.get("planned_method") == "offline_policy_value_sensitivity":
        mapping.extend((field, field) for field in (
            "evaluation_mode", "logged_action_field", "action_values", "reward_field",
            "propensity_field", "bootstrap_unit_field", "estimators", "primary_estimator", "q_logged_field",
            "policy_specs", "minimum_effective_sample_size", "maximum_importance_weight",
            "confidence_level", "bootstrap_replicates", "bootstrap_seed",
            "weight_clip_grid", "propensity_floor_grid",
        ))
    mismatches: list[str] = []
    for binding_key, target_key in mapping:
        actual = binding.get(binding_key)
        expected = target.get(target_key)
        if binding_key == "design_evidence_refs":
            if sorted(actual or []) != sorted(expected or []):
                mismatches.append(binding_key)
        elif actual != expected:
            mismatches.append(binding_key)
    return list(dict.fromkeys(mismatches))


def adapt_deep_evidence(payload: Any, base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        rows = payload["cards"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("deep evidence cards must be a list or an object containing cards")
    output: dict[str, dict[str, Any]] = {}
    digest_cache: dict[Path, str] = {}
    content_cache: dict[tuple[str, Path], Any] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"evidence card {index} must be an object")
        evidence_id = str(row.get("evidence_id") or row.get("id") or "").strip()
        if not evidence_id or evidence_id in output:
            raise ValueError(f"evidence card id is missing or duplicated: {evidence_id or index}")
        status = str(row.get("status") or "").strip()
        explicit = row.get("verified")
        verified = explicit if isinstance(explicit, bool) else status in VERIFIED_STATUSES
        claim = str(row.get("claim") or row.get("observed_fact") or "").strip()
        source = row.get("source") if row.get("source") is not None else row.get("source_ref")
        source_path = Path(str(source or ""))
        if source_path and not source_path.is_absolute() and base_dir is not None:
            source_path = (base_dir / source_path).resolve()
        declared_sha256 = str(row.get("source_sha256") or "").strip().lower()
        locator = row.get("locator")
        unit_id = str(row.get("unit_id") or "").strip()
        independence_group = str(row.get("independence_group") or "").strip()
        family_id = str(row.get("family_id") or "").strip()
        lane = str(row.get("lane") or row.get("type") or "").strip()
        directness = str(row.get("directness") or "").strip()
        result_contract_version = str(row.get("result_contract_version") or "").strip()
        result_status = str(row.get("result_status") or "").strip()
        result_decision_question: str | None = None
        result_analysis_binding: dict[str, Any] | None = None
        result_binding_status: str | None = None
        result_coverage_status: str | None = None
        result_bound_statement: str | None = None
        result_bound_measurement: dict[str, Any] | None = None
        result_bound_claim: str | None = None
        result_data_evidence_refs: list[str] = []
        result_data_sha256: str | None = None
        result_source_spec: dict[str, Any] | None = None
        design_binding = row.get("design_binding")
        identification_check_binding = row.get("identification_check_binding")
        verification_errors: list[str] = []
        required_values = {
            "claim": claim,
            "source": source,
            "unit_id": unit_id,
            "independence_group": independence_group,
            "family_id": family_id,
            "lane": lane,
            "directness": directness,
        }
        if verified:
            for key, value in required_values.items():
                if value in (None, "", []):
                    verification_errors.append(f"{key}_missing")
            if not isinstance(locator, dict):
                verification_errors.append("locator_missing")
            if directness not in {"direct", "derived", "source_stated"}:
                verification_errors.append("directness_invalid")
            if not source_path.is_file():
                verification_errors.append("source_file_missing")
            else:
                if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256):
                    verification_errors.append("source_sha256_missing_or_invalid")
                else:
                    actual_sha256 = digest_cache.get(source_path)
                    if actual_sha256 is None:
                        actual_sha256 = file_sha256(source_path)
                        digest_cache[source_path] = actual_sha256
                if re.fullmatch(r"[0-9a-f]{64}", declared_sha256) and actual_sha256 != declared_sha256:
                    verification_errors.append("source_sha256_mismatch")
                verification_errors.extend(_verify_locator(source_path, locator, content_cache))
                if lane in DESIGN_LANES:
                    required_design_fields = (
                        "analysis_unit", "outcome_name", "outcome_field", "intervention",
                        "comparator", "group_field", "intervention_value", "comparator_value",
                        "assignment_mechanism", "identification_strategy", "estimand", "estimator",
                    )
                    if not isinstance(design_binding, dict) or any(
                        design_binding.get(field) in (None, "")
                        for field in required_design_fields
                    ):
                        verification_errors.append("design_binding_missing_or_incomplete")
                    elif lane == "identification_check" and (
                        not isinstance(identification_check_binding, dict)
                        or not str(identification_check_binding.get("check_name") or "").strip()
                        or identification_check_binding.get("status") not in {
                            "supported", "uncertain", "violated"
                        }
                    ):
                        verification_errors.append("identification_check_binding_missing")
                    expected_locator_value = (
                        {
                            "design": design_binding,
                            "check": identification_check_binding,
                        }
                        if lane == "identification_check" else design_binding
                    )
                    if not isinstance(locator, dict) or locator.get("type") != "json_pointer" or (
                        locator.get("expected") != expected_locator_value
                    ):
                        verification_errors.append("design_binding_not_source_located")
                if lane == "analysis_result":
                    if directness != "derived":
                        verification_errors.append("analysis_result_must_be_derived")
                    if not result_contract_version or not result_status:
                        verification_errors.append("analysis_result_contract_or_status_missing")
                    elif source_path.suffix.lower() != ".json":
                        verification_errors.append("analysis_result_source_must_be_json")
                    else:
                        try:
                            result_payload = content_cache.get(("json", source_path))
                            if result_payload is None:
                                result_payload = load_json(source_path)
                                content_cache[("json", source_path)] = result_payload
                            actual_contract = str(result_payload.get("contract_version") or "")
                            actual_status = str(
                                result_payload.get("execution_status") or result_payload.get("status") or ""
                            )
                            result_decision_question = str(
                                result_payload.get("decision_question") or ""
                            ).strip() or None
                            raw_binding = result_payload.get("analysis_binding")
                            raw_data_refs = result_payload.get("data_evidence_refs")
                            data_profile = result_payload.get("data_profile")
                            if actual_contract != result_contract_version:
                                verification_errors.append("analysis_result_contract_mismatch")
                            if actual_contract not in TRUSTED_RESULT_CONTRACTS:
                                verification_errors.append("analysis_result_contract_not_supported")
                            if actual_status != result_status:
                                verification_errors.append("analysis_result_status_mismatch")
                            if actual_status not in {"completed", "succeeded"}:
                                verification_errors.append("analysis_result_not_successful")
                            if not result_decision_question:
                                verification_errors.append("analysis_result_decision_question_missing")
                            if not isinstance(raw_data_refs, list) or not raw_data_refs or not all(
                                isinstance(item, str) and item.strip() for item in raw_data_refs
                            ):
                                verification_errors.append("analysis_result_data_evidence_missing")
                            else:
                                result_data_evidence_refs = [item.strip() for item in raw_data_refs]
                            if not isinstance(data_profile, dict) or not re.fullmatch(
                                r"[0-9a-fA-F]{64}", str(data_profile.get("sha256") or "")
                            ):
                                verification_errors.append("analysis_result_data_sha256_missing")
                            else:
                                result_data_sha256 = str(data_profile["sha256"]).lower()
                            if not isinstance(raw_binding, dict):
                                verification_errors.append("analysis_result_binding_missing")
                            else:
                                result_analysis_binding = copy.deepcopy(raw_binding)
                                for field in (
                                    "analysis_layer", "target", "validation_type", "method",
                                    "component_id", "outcome_field",
                                ):
                                    if result_analysis_binding.get(field) in (None, "", []):
                                        verification_errors.append(f"analysis_result_binding_{field}_missing")
                                binding_layer = str(result_analysis_binding.get("analysis_layer") or "")
                                binding_validation = str(result_analysis_binding.get("validation_type") or "")
                                if binding_validation not in RESULT_LAYER_VALIDATIONS.get(binding_layer, set()):
                                    verification_errors.append("analysis_result_binding_type_invalid")
                                design_refs = result_analysis_binding.get("design_evidence_refs")
                                if actual_contract == LEGACY_RESULT_CONTRACT and (
                                    not isinstance(design_refs, list) or not design_refs or not all(
                                        isinstance(item, str) and item.strip() for item in design_refs
                                    )
                                ):
                                    verification_errors.append("analysis_result_binding_design_evidence_invalid")
                                if actual_contract in DEEP_EXECUTION_RESULT_CONTRACTS and binding_layer not in {
                                    "heterogeneity", "mechanism", "predictive", "decision"
                                }:
                                    verification_errors.append("analysis_result_binding_layer_not_supported_by_contract")
                                if actual_contract == LEGACY_RESULT_CONTRACT and binding_layer not in {
                                    "predictive", "causal", "decision"
                                }:
                                    verification_errors.append("analysis_result_binding_layer_not_supported_by_contract")
                                if binding_layer == "causal" and any(
                                    result_analysis_binding.get(field) in (None, "")
                                    for field in (
                                        "identification_strategy", "intervention", "comparator",
                                        "group_field", "intervention_value", "comparator_value",
                                    )
                                ):
                                    verification_errors.append("analysis_result_causal_binding_incomplete")
                                if binding_layer == "predictive":
                                    if any(
                                        not str(result_analysis_binding.get(field) or "").strip()
                                        for field in (
                                            "validation_design", "horizon", "horizon_unit", "cutoff",
                                            "metric", "baseline_model", "baseline_kind", "cutoff_mode",
                                        )
                                    ) or not isinstance(result_analysis_binding.get("horizon_steps"), int):
                                        verification_errors.append("analysis_result_predictive_binding_incomplete")
                                if binding_layer == "decision" and any(
                                    not str(result_analysis_binding.get(field) or "").strip()
                                    for field in ("evidence_basis", "utility_metric", "decision_threshold")
                                ):
                                    verification_errors.append("analysis_result_decision_binding_incomplete")
                                source_spec = result_payload.get("source_spec")
                                if not isinstance(source_spec, dict):
                                    verification_errors.append(
                                        "analysis_result_source_spec_missing"
                                    )
                                else:
                                    result_source_spec = copy.deepcopy(source_spec)
                                if actual_contract == LEGACY_RESULT_CONTRACT:
                                    components = [
                                        component
                                        for dimension in (result_payload.get("dimensions") or {}).values()
                                        if isinstance(dimension, dict)
                                        for component in (dimension.get("components") or [])
                                        if isinstance(component, dict)
                                    ]
                                    bound_component = next(
                                        (
                                            component for component in components
                                            if str(component.get("component_id") or "")
                                            == str(result_analysis_binding.get("component_id") or "")
                                        ),
                                        None,
                                    )
                                    if not bound_component:
                                        verification_errors.append("analysis_result_bound_component_missing")
                                    elif str((bound_component.get("measurement") or {}).get("kind") or "") != str(
                                        result_analysis_binding.get("method") or ""
                                    ):
                                        verification_errors.append("analysis_result_bound_method_mismatch")
                                    elif bound_component.get("status") != "supported":
                                        verification_errors.append("analysis_result_bound_component_not_supported")
                                    else:
                                        measurement_spec = bound_component.get("measurement_spec")
                                        if not isinstance(measurement_spec, dict):
                                            verification_errors.append(
                                                "analysis_result_measurement_spec_missing"
                                            )
                                        elif measurement_spec.get("field") != result_analysis_binding.get(
                                            "outcome_field"
                                        ):
                                            verification_errors.append(
                                                "analysis_result_outcome_field_mismatch"
                                            )
                                        if binding_layer == "causal" and isinstance(measurement_spec, dict):
                                            validation_type = result_analysis_binding.get("validation_type")
                                            mapping = (
                                                (
                                                    ("group_field", "group_field"),
                                                    ("group_a", "intervention_value"),
                                                    ("group_b", "comparator_value"),
                                                )
                                                if validation_type == "randomized_experiment"
                                                else (
                                                    ("group_field", "group_field"),
                                                    ("treated_value", "intervention_value"),
                                                    ("control_value", "comparator_value"),
                                                )
                                            )
                                            for measurement_key, binding_key in mapping:
                                                if measurement_spec.get(measurement_key) != result_analysis_binding.get(binding_key):
                                                    verification_errors.append(
                                                        "analysis_result_treatment_mapping_mismatch:"
                                                        + binding_key
                                                    )
                                        result_bound_statement = str(
                                            bound_component.get("statement") or ""
                                        ).strip() or None
                                        measurement = bound_component.get("measurement")
                                        if not result_bound_statement or not isinstance(measurement, dict):
                                            verification_errors.append("analysis_result_bound_output_incomplete")
                                        else:
                                            result_bound_measurement = copy.deepcopy(measurement)
                                            result_bound_claim = _canonical_result_claim(
                                                result_analysis_binding.get("target"),
                                                result_analysis_binding.get("method"),
                                                measurement,
                                            )
                                        result_coverage_status = "completed"
                                        result_binding_status = "supported"
                                elif actual_contract in DEEP_EXECUTION_RESULT_CONTRACTS:
                                    result_coverage_status = str(
                                        result_payload.get("coverage_status") or ""
                                    ).strip() or None
                                    if result_coverage_status not in {
                                        "completed", "inconclusive", "unverifiable"
                                    }:
                                        verification_errors.append(
                                            "analysis_result_coverage_status_invalid"
                                        )
                                    if str(result_payload.get("execution_id") or "") != str(
                                        result_analysis_binding.get("component_id") or ""
                                    ):
                                        verification_errors.append(
                                            "analysis_result_component_binding_mismatch"
                                        )
                                    result_object = result_payload.get("result")
                                    if not isinstance(result_object, dict) or "primary_value" not in result_object:
                                        verification_errors.append(
                                            "analysis_result_bound_output_incomplete"
                                        )
                                    else:
                                        primary = result_object.get("primary_value")
                                        result_bound_statement = str(
                                            result_analysis_binding.get("target") or ""
                                        ).strip() or None
                                        result_bound_measurement = {"value": copy.deepcopy(primary)}
                                        if result_coverage_status == "completed":
                                            result_bound_claim = _canonical_result_claim(
                                                result_analysis_binding.get("target"),
                                                result_analysis_binding.get("method"),
                                                result_bound_measurement,
                                            )
                                            result_binding_status = "supported"
                                        elif result_coverage_status == "inconclusive":
                                            result_binding_status = "inconclusive"
                        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
                            verification_errors.append("analysis_result_unreadable")
        if verification_errors:
            verified = False
        output[evidence_id] = {
            "verified": verified,
            "verification_errors": verification_errors,
            "claim": claim,
            "source": str(source_path) if str(source_path) else source,
            "source_sha256": declared_sha256,
            "locator": locator,
            "unit_id": unit_id,
            "independence_group": independence_group,
            "family_id": family_id,
            "lane": lane,
            "directness": directness,
            "design_binding": copy.deepcopy(design_binding) if isinstance(design_binding, dict) else None,
            "identification_check_binding": copy.deepcopy(
                identification_check_binding
            ) if isinstance(identification_check_binding, dict) else None,
            "result_contract_version": result_contract_version or None,
            "result_status": result_status or None,
            "result_decision_question": result_decision_question,
            "result_analysis_binding": result_analysis_binding,
            "result_binding_status": result_binding_status,
            "result_coverage_status": result_coverage_status,
            "result_bound_statement": result_bound_statement,
            "result_bound_measurement": result_bound_measurement,
            "result_bound_claim": result_bound_claim,
            "result_data_evidence_refs": result_data_evidence_refs,
            "result_data_sha256": result_data_sha256,
            "result_source_spec": result_source_spec,
            "caveat": row.get("caveat") or row.get("cannot_prove"),
            "status": status or ("verified" if verified else "unverified"),
        }
    for evidence_id, card in output.items():
        if card.get("verified") is not True or card.get("lane") != "analysis_result":
            continue
        binding = card.get("result_analysis_binding") or {}
        for ref in binding.get("design_evidence_refs") or []:
            referenced = output.get(ref)
            if not referenced or referenced.get("verified") is not True:
                card["verification_errors"].append(
                    f"analysis_result_design_evidence_invalid:{ref}"
                )
        data_refs = card.get("result_data_evidence_refs") or []
        verified_data_cards = [
            output.get(ref) for ref in data_refs
            if output.get(ref) and output[ref].get("verified") is True
        ]
        for ref in data_refs:
            if ref not in output or output[ref].get("verified") is not True:
                card["verification_errors"].append(
                    f"analysis_result_data_evidence_invalid:{ref}"
                )
        if not verified_data_cards or card.get("result_data_sha256") not in {
            str(item.get("source_sha256") or "").lower() for item in verified_data_cards
        }:
            card["verification_errors"].append("analysis_result_data_sha256_unbound")
        source_spec = card.get("result_source_spec")
        source_info = source_spec.get("data_source") if isinstance(source_spec, dict) else None
        declared_path = str((source_info or {}).get("path") or "").strip()
        result_parent = Path(str(card.get("source") or "")).parent
        is_unc_path = declared_path.startswith("\\\\") or declared_path.startswith("//")
        if is_unc_path:
            card["verification_errors"].append("analysis_result_source_path_unc_rejected")
            candidate_key = ""
        elif declared_path:
            candidate_path = Path(declared_path)
            if not candidate_path.is_absolute():
                candidate_path = result_parent / candidate_path
            candidate_key = os.path.normcase(os.path.abspath(str(candidate_path)))
        else:
            candidate_key = ""
        allowed_keys = {
            os.path.normcase(os.path.abspath(str(item.get("source") or "")))
            for item in verified_data_cards
        }
        if not candidate_key or candidate_key not in allowed_keys:
            card["verification_errors"].append("analysis_result_source_path_unbound")
        if not card["verification_errors"]:
            result_payload = load_json(Path(str(card["source"])))
            if card.get("result_contract_version") == LEGACY_RESULT_CONTRACT:
                from run_hypothesis_experiment import run_hypothesis_experiment

                rerun = run_hypothesis_experiment(copy.deepcopy(source_spec), result_parent)
                rerun_fields = (
                    "contract_version", "experiment_id", "decision_question", "mode",
                    "analysis_binding", "data_evidence_refs", "execution_status", "errors",
                    "data_profile", "dimensions", "summary",
                )
            else:
                from run_deep_analysis_execution import run_deep_analysis_execution

                rerun = run_deep_analysis_execution(copy.deepcopy(source_spec), result_parent)
                rerun_fields = (
                    "contract_version", "execution_id", "decision_question",
                    "analysis_binding", "data_evidence_refs", "execution_status",
                    "coverage_status", "errors", "data_profile", "result",
                )
            for field in rerun_fields:
                if result_payload.get(field) != rerun.get(field):
                    card["verification_errors"].append(
                        f"analysis_result_rerun_mismatch:{field}"
                    )
        if card["verification_errors"]:
            card["verified"] = False
            card["result_binding_status"] = None
    return output


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _list_of_text(value: Any, field: str, errors: list[str], *, required: bool = True) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    output = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(output) != len(value):
        errors.append(f"{field} must contain non-empty strings")
    if required and not output:
        errors.append(f"{field} must not be empty")
    return output


def _evidence_errors(refs: list[str], evidence: dict[str, dict[str, Any]], prefix: str) -> list[str]:
    errors: list[str] = []
    for ref in refs:
        if ref not in evidence:
            errors.append(f"{prefix}.unknown_evidence:{ref}")
        elif evidence[ref]["verified"] is not True:
            errors.append(f"{prefix}.unverified_evidence:{ref}")
    return errors


def _selected_family(scope_gate: dict[str, Any]) -> str | None:
    selection = scope_gate.get("selection") or {}
    if selection.get("scope_type") == "family":
        return str(scope_gate.get("selected_family_id") or selection.get("scope_id") or "").strip() or None
    return None


def _recompile_and_verify_plan(
    analysis_plan: dict[str, Any],
    evidence_payload: Any,
    evidence_base_dir: Path | None,
) -> dict[str, Any]:
    source_spec = analysis_plan.get("source_question_spec")
    if not isinstance(source_spec, dict):
        raise ValueError("deep analysis plan must contain its source_question_spec")
    # Local import avoids a module-level cycle: the question compiler uses the
    # evidence adapter above, while this function is called only after loading.
    from compile_deep_analysis_question import compile_deep_analysis_question

    recompiled = compile_deep_analysis_question(
        copy.deepcopy(source_spec), evidence_payload, evidence_base_dir
    )
    if recompiled.get("contract_status") != "compiled":
        raise ValueError("deep analysis plan source_question_spec no longer compiles")
    mismatches = [
        field for field in PLAN_INTEGRITY_FIELDS
        if analysis_plan.get(field) != recompiled.get(field)
    ]
    if mismatches:
        raise ValueError(
            "deep analysis plan differs from a fresh compilation:"
            + ",".join(mismatches)
        )
    return recompiled


def compile_findings(
    candidate_payload: Any,
    evidence_payload: Any,
    scope_gate: dict[str, Any],
    evidence_base_dir: Path | None = None,
    analysis_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate_payload, dict):
        raise ValueError("finding candidates must be an object")
    decision_question = str(candidate_payload.get("decision_question") or "").strip()
    if not decision_question:
        raise ValueError("decision_question is required and must preserve the user's original request")
    if scope_gate.get("contract_version") != "data-lens-corpus-scope-gate/1.0":
        raise ValueError("unsupported corpus scope gate")
    scope_ready = scope_gate.get("deep_analysis_allowed") is True and scope_gate.get("next_action") == "analysis_ready"
    if str(scope_gate.get("decision_question") or "").strip() != decision_question:
        raise ValueError("finding decision_question must exactly match the corpus scope gate")
    plan_permissions: dict[str, Any] = {}
    plan_targets: dict[str, Any] = {}
    plan_layers: dict[str, Any] = {}
    plan_required_layers: list[str] = []
    plan_required_layers_ready = True
    plan_required_result_layers: list[str] = []
    verified_plan: dict[str, Any] | None = None
    if analysis_plan is not None:
        if not isinstance(analysis_plan, dict) or analysis_plan.get("contract_version") != "data-lens-deep-analysis-plan/0.1":
            raise ValueError("unsupported deep analysis plan")
        if analysis_plan.get("contract_status") != "compiled":
            raise ValueError("deep analysis plan must be compiled before finding adoption")
        if str(analysis_plan.get("decision_question") or "").strip() != decision_question:
            raise ValueError("deep analysis plan decision_question must exactly match finding candidates")
        verified_plan = _recompile_and_verify_plan(
            analysis_plan, evidence_payload, evidence_base_dir
        )
        plan_permissions = verified_plan.get("claim_permissions") or {}
        if not isinstance(plan_permissions, dict):
            raise ValueError("deep analysis plan claim_permissions must be an object")
        plan_targets = verified_plan.get("analysis_targets") or {}
        if not isinstance(plan_targets, dict):
            raise ValueError("deep analysis plan analysis_targets must be an object")
        plan_layers = verified_plan.get("analysis_layers") or {}
        plan_required_layers = list((verified_plan.get("summary") or {}).get("required_layers") or [])
        plan_required_layers_ready = bool(plan_required_layers) and all(
            isinstance(plan_layers.get(layer), dict)
            and plan_layers[layer].get("status") == "ready"
            for layer in plan_required_layers
        )
        plan_required_result_layers = [
            layer for layer in plan_required_layers
            if layer in SUBSTANTIVE_RESULT_LAYERS
        ]
    selected_family = _selected_family(scope_gate)
    request, request_errors = _request(candidate_payload)
    evidence = adapt_deep_evidence(evidence_payload, evidence_base_dir)
    rows = candidate_payload.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("candidates must be an array")
    if len(rows) > 12:
        raise ValueError("deep finding compilation accepts at most 12 candidates")
    proposed_count = sum(
        1 for row in rows
        if isinstance(row, dict) and str(row.get("proposed_status") or "").lower() in ADOPT_VALUES
    )
    if proposed_count > 8:
        raise ValueError("deep finding compilation accepts at most 8 proposed adoptions")

    seen: set[str] = set()
    compiled: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"candidate {index} must be an object")
        finding_id = _text(row, "finding_id") or f"invalid-{index + 1}"
        contract_errors: list[str] = []
        if finding_id in seen:
            contract_errors.append("finding_id is duplicated")
        seen.add(finding_id)
        for field in ("finding_id", "title", "claim", "analysis_unit", "decision_relevance", "baseline", "decision_delta", "confidence"):
            if not _text(row, field):
                contract_errors.append(f"{field} is required")
        claim_level = _text(row, "claim_level")
        if claim_level not in CLAIM_LEVELS:
            contract_errors.append("claim_level is invalid")
        published_wording = "\n".join(
            _text(row, field)
            for field in ("title", "claim", "decision_relevance", "baseline", "decision_delta")
        )
        if claim_level != "causal_effect" and has_explicit_causal_wording(published_wording):
            if claim_level != "mechanism_hypothesis" or not has_hypothesis_qualifier(published_wording):
                contract_errors.append("explicit causal wording requires causal_effect evidence")
        if claim_level != "prediction" and has_explicit_prediction_wording(published_wording):
            contract_errors.append("explicit future prediction requires prediction evidence")
        if claim_level != "decision_rule" and has_explicit_action_directive(published_wording):
            contract_errors.append("action directive requires decision_rule evidence")
        if claim_level == "relationship" and not has_noncausal_relation_wording(published_wording):
            contract_errors.append("relationship wording must explicitly remain non-causal")
        permission_family = CLAIM_PERMISSION.get(claim_level)
        if analysis_plan is not None and permission_family and plan_permissions.get(permission_family) != "allowed":
            contract_errors.append(
                f"deep analysis plan does not allow {permission_family} claims"
            )
        if claim_level in ADVANCED_CLAIM_LEVELS and analysis_plan is None:
            contract_errors.append("advanced claim levels require a compiled deep analysis plan")
        confidence = _text(row, "confidence")
        if confidence not in {"high", "medium", "low"}:
            contract_errors.append("confidence is invalid")
        proposed_status = _text(row, "proposed_status").lower()
        if proposed_status not in ADOPT_VALUES | REJECT_VALUES:
            contract_errors.append("proposed_status must be adopted or rejected")
        rejection_reason = _text(row, "rejection_reason")
        if proposed_status in REJECT_VALUES and not rejection_reason:
            contract_errors.append("rejected finding requires rejection_reason")
        boundaries = _list_of_text(row.get("boundaries"), "boundaries", contract_errors)
        support_refs = _list_of_text(row.get("supporting_evidence_refs"), "supporting_evidence_refs", contract_errors)
        coverage_result_refs = _list_of_text(
            row.get("analysis_coverage_evidence_refs", []),
            "analysis_coverage_evidence_refs",
            contract_errors,
            required=False,
        )

        coverage = row.get("coverage")
        if not isinstance(coverage, dict):
            coverage = {}
            contract_errors.append("coverage must be an object")
        strategy = str(coverage.get("strategy") or "").strip()
        eligible_units = coverage.get("eligible_units")
        reviewed_units = coverage.get("reviewed_units")
        declared_groups = _list_of_text(coverage.get("independent_source_groups"), "coverage.independent_source_groups", contract_errors)
        limitations = _list_of_text(coverage.get("limitations"), "coverage.limitations", contract_errors, required=False)
        if not strategy:
            contract_errors.append("coverage.strategy is required")
        if eligible_units is not None and (not isinstance(eligible_units, int) or isinstance(eligible_units, bool) or eligible_units < 0):
            contract_errors.append("coverage.eligible_units must be null or a non-negative integer")
        if not isinstance(reviewed_units, int) or isinstance(reviewed_units, bool) or reviewed_units < 1:
            contract_errors.append("coverage.reviewed_units must be a positive integer")
        if isinstance(eligible_units, int) and isinstance(reviewed_units, int) and reviewed_units > eligible_units:
            contract_errors.append("coverage.reviewed_units exceeds eligible_units")

        counter = row.get("counterexample_search")
        if not isinstance(counter, dict):
            counter = {}
            contract_errors.append("counterexample_search must be an object")
        counter_status = str(counter.get("status") or "not_completed")
        counter_description = str(counter.get("description") or "").strip()
        counter_refs = _list_of_text(counter.get("evidence_refs"), "counterexample_search.evidence_refs", contract_errors, required=False)
        if counter_status not in COUNTER_STATUSES:
            contract_errors.append("counterexample_search.status is invalid")
        if not counter_description:
            contract_errors.append("counterexample_search.description is required")
        if counter_status != "not_completed" and not counter_refs:
            contract_errors.append("a completed counterexample search requires evidence of the search or observed counterexamples")

        alternatives = row.get("alternative_explanations")
        if not isinstance(alternatives, list):
            alternatives = []
            contract_errors.append("alternative_explanations must be an array")
        normalized_alternatives: list[dict[str, Any]] = []
        alternative_refs: list[str] = []
        for alt_index, alternative in enumerate(alternatives):
            if not isinstance(alternative, dict):
                contract_errors.append(f"alternative_explanations[{alt_index}] must be an object")
                continue
            explanation = str(alternative.get("explanation") or "").strip()
            status = str(alternative.get("status") or "").strip()
            discriminating_test = str(alternative.get("discriminating_test") or "").strip()
            refs = _list_of_text(alternative.get("evidence_refs"), f"alternative_explanations[{alt_index}].evidence_refs", contract_errors, required=False)
            discriminating_refs = _list_of_text(alternative.get("discriminating_evidence_refs"), f"alternative_explanations[{alt_index}].discriminating_evidence_refs", contract_errors, required=False)
            if not explanation:
                contract_errors.append(f"alternative_explanations[{alt_index}].explanation is required")
            if status not in ALTERNATIVE_STATUSES:
                contract_errors.append(f"alternative_explanations[{alt_index}].status is invalid")
            if not discriminating_test:
                contract_errors.append(f"alternative_explanations[{alt_index}].discriminating_test is required")
            alternative_refs.extend(refs + discriminating_refs)
            normalized_alternatives.append({
                "explanation": explanation,
                "status": status,
                "discriminating_test": discriminating_test,
                "evidence_refs": refs,
                "discriminating_evidence_refs": discriminating_refs,
            })
        if claim_level in INFERENCE_LEVELS and not normalized_alternatives:
            contract_errors.append("inference-level findings require at least one competing explanation")

        robustness = row.get("robustness_checks")
        if not isinstance(robustness, list):
            robustness = []
            contract_errors.append("robustness_checks must be an array")
        normalized_robustness: list[dict[str, Any]] = []
        robustness_refs: list[str] = []
        for check_index, check in enumerate(robustness):
            if not isinstance(check, dict):
                contract_errors.append(f"robustness_checks[{check_index}] must be an object")
                continue
            check_id = str(check.get("check_id") or "").strip()
            description = str(check.get("description") or "").strip()
            result = str(check.get("result") or "").strip()
            status = str(check.get("status") or "").strip()
            refs = _list_of_text(check.get("evidence_refs"), f"robustness_checks[{check_index}].evidence_refs", contract_errors, required=False)
            if not check_id or not description or not result:
                contract_errors.append(f"robustness_checks[{check_index}] requires check_id, description, and result")
            if status not in ROBUSTNESS_STATUSES:
                contract_errors.append(f"robustness_checks[{check_index}].status is invalid")
            if status != "not_applicable" and not refs:
                contract_errors.append(f"robustness_checks[{check_index}] requires evidence for a completed check")
            robustness_refs.extend(refs)
            normalized_robustness.append({
                "check_id": check_id,
                "description": description,
                "result": result,
                "status": status,
                "evidence_refs": refs,
            })

        claim_design = row.get("claim_design")
        normalized_claim_design: dict[str, Any] | None = None
        design_refs: list[str] = []
        bound_result_claims: list[str] = []
        if claim_level in ADVANCED_CLAIM_LEVELS:
            if not isinstance(claim_design, dict):
                contract_errors.append("advanced claim levels require claim_design")
                claim_design = {}
            expected_layer = CLAIM_PERMISSION.get(claim_level)
            analysis_layer = _text(claim_design, "analysis_layer")
            target = _text(claim_design, "target")
            method = _text(claim_design, "method")
            validation_type = _text(claim_design, "validation_type")
            validation_status = _text(claim_design, "validation_status")
            assumptions = _list_of_text(
                claim_design.get("assumptions"), "claim_design.assumptions", contract_errors
            )
            design_refs = _list_of_text(
                claim_design.get("result_evidence_refs"),
                "claim_design.result_evidence_refs",
                contract_errors,
            )
            if analysis_layer != expected_layer:
                contract_errors.append("claim_design.analysis_layer does not match claim_level")
            target_spec = plan_targets.get(expected_layer)
            expected_target = _text(target_spec, "target") if isinstance(target_spec, dict) else ""
            if not expected_target or target != expected_target:
                contract_errors.append("claim_design.target does not match the compiled analysis target")
            if not target or not method:
                contract_errors.append("claim_design requires target and method")
            if validation_type not in ADVANCED_VALIDATION_TYPES.get(claim_level, set()):
                contract_errors.append("claim_design.validation_type is incompatible with claim_level")
            if claim_level == "causal_effect":
                causal_target = plan_targets.get("causal") if isinstance(plan_targets, dict) else None
                identification_strategy = (
                    str(causal_target.get("identification_strategy") or "")
                    if isinstance(causal_target, dict) else ""
                )
                expected_validation = (
                    "randomized_experiment"
                    if identification_strategy == "randomized"
                    else "identified_observational_estimate"
                )
                if validation_type != expected_validation:
                    contract_errors.append(
                        "claim_design.validation_type does not match the compiled identification strategy"
                    )
            if validation_status != "supported":
                contract_errors.append("advanced claim_design must have supported validation_status")
            for ref in design_refs:
                card = evidence.get(ref)
                if card and card.get("verified") is True and (
                    card.get("lane") != "analysis_result" or card.get("directness") != "derived"
                ):
                    contract_errors.append(
                        f"claim_design result evidence must be a derived analysis_result:{ref}"
                    )
                if card and card.get("verified") is True and card.get("result_decision_question") != decision_question:
                    contract_errors.append(
                        f"claim_design result decision_question mismatch:{ref}"
                    )
                if card and card.get("verified") is True:
                    binding = card.get("result_analysis_binding")
                    if not isinstance(binding, dict) or card.get("result_binding_status") != "supported":
                        contract_errors.append(f"claim_design result binding is not supported:{ref}")
                    else:
                        bound_claim = str(card.get("result_bound_claim") or "").strip()
                        if not bound_claim:
                            contract_errors.append(
                                f"claim_design result has no canonical measured claim:{ref}"
                            )
                        else:
                            bound_result_claims.append(bound_claim)
                        for key, expected in (
                            ("analysis_layer", analysis_layer),
                            ("target", target),
                            ("validation_type", validation_type),
                            ("method", method),
                        ):
                            if binding.get(key) != expected:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:{key}"
                                )
                        for mismatch in _binding_plan_mismatches(
                            binding, analysis_layer, plan_targets
                        ):
                            contract_errors.append(
                                f"claim_design result binding mismatch:{ref}:{mismatch}"
                            )
                        planned_data_refs = set(plan_targets.get("data_evidence_refs") or [])
                        actual_data_refs = set(card.get("result_data_evidence_refs") or [])
                        if not actual_data_refs or not actual_data_refs.issubset(planned_data_refs):
                            contract_errors.append(
                                f"claim_design result data evidence is outside the compiled plan:{ref}"
                            )
                        if analysis_layer == "causal":
                            causal_target = plan_targets.get("causal") if isinstance(plan_targets, dict) else None
                            expected_identification = (
                                causal_target.get("identification_strategy")
                                if isinstance(causal_target, dict) else None
                            )
                            if binding.get("identification_strategy") != expected_identification:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:identification_strategy"
                                )
                            expected_method = (
                                causal_target.get("planned_method")
                                if isinstance(causal_target, dict) else None
                            )
                            if method != expected_method:
                                contract_errors.append(
                                    f"claim_design method does not match compiled causal estimator:{ref}"
                                )
                            for key in (
                                "intervention", "comparator", "outcome_field", "group_field",
                                "intervention_value", "comparator_value",
                            ):
                                expected_value = (
                                    causal_target.get(key) if isinstance(causal_target, dict) else None
                                )
                                if binding.get(key) != expected_value:
                                    contract_errors.append(
                                        f"claim_design result binding mismatch:{ref}:{key}"
                                    )
                            expected_design_refs = (
                                causal_target.get("design_evidence_refs")
                                if isinstance(causal_target, dict) else []
                            ) or []
                            if sorted(binding.get("design_evidence_refs") or []) != sorted(expected_design_refs):
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:design_evidence_refs"
                                )
                        elif analysis_layer == "predictive":
                            predictive_target = plan_targets.get("predictive") if isinstance(plan_targets, dict) else None
                            expected_validation_design = (
                                predictive_target.get("validation")
                                if isinstance(predictive_target, dict) else None
                            )
                            if binding.get("validation_design") != expected_validation_design:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:validation_design"
                                )
                            if binding.get("outcome_field") != (
                                predictive_target.get("outcome_field")
                                if isinstance(predictive_target, dict) else None
                            ):
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:outcome_field"
                                )
                            for key in (
                                "horizon", "horizon_steps", "horizon_unit", "cutoff", "metric",
                                "baseline_model", "baseline_kind", "cutoff_mode",
                            ):
                                expected_value = (
                                    predictive_target.get(key)
                                    if isinstance(predictive_target, dict) else None
                                )
                                if binding.get(key) != expected_value:
                                    contract_errors.append(
                                        f"claim_design result binding mismatch:{ref}:{key}"
                                    )
                        elif analysis_layer == "decision":
                            decision_target = plan_targets.get("decision") if isinstance(plan_targets, dict) else None
                            expected_basis = (
                                decision_target.get("evidence_basis")
                                if isinstance(decision_target, dict) else None
                            )
                            expected_threshold = (
                                decision_target.get("decision_threshold")
                                if isinstance(decision_target, dict) else None
                            )
                            if binding.get("evidence_basis") != expected_basis:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:evidence_basis"
                                )
                            expected_utility = (
                                decision_target.get("utility_metric")
                                if isinstance(decision_target, dict) else None
                            )
                            if binding.get("utility_metric") != expected_utility:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:utility_metric"
                                )
                            if binding.get("decision_threshold") != expected_threshold:
                                contract_errors.append(
                                    f"claim_design result binding mismatch:{ref}:decision_threshold"
                                )
            if bound_result_claims and any(
                claim != _text(row, "claim") for claim in bound_result_claims
            ):
                contract_errors.append(
                    "advanced claim must equal the result's canonical measured claim"
                )
            normalized_claim_design = {
                "analysis_layer": analysis_layer,
                "target": target,
                "method": method,
                "assumptions": assumptions,
                "validation_type": validation_type,
                "validation_status": validation_status,
                "result_evidence_refs": design_refs,
            }

        if coverage_result_refs and analysis_plan is None:
            contract_errors.append(
                "analysis_coverage_evidence_refs require a compiled deep analysis plan"
            )
        for ref in coverage_result_refs:
            card = evidence.get(ref)
            if card and card.get("verified") is True and (
                card.get("lane") != "analysis_result" or card.get("directness") != "derived"
            ):
                contract_errors.append(
                    f"analysis coverage evidence must be a derived analysis_result:{ref}"
                )
            if card and card.get("verified") is True:
                if card.get("result_decision_question") != decision_question:
                    contract_errors.append(
                        f"analysis coverage decision_question mismatch:{ref}"
                    )
                binding = card.get("result_analysis_binding")
                if (
                    not isinstance(binding, dict)
                    or card.get("result_binding_status") != "supported"
                    or card.get("result_coverage_status") != "completed"
                ):
                    contract_errors.append(
                        f"analysis coverage result is not completed and supported:{ref}"
                    )
                    continue
                layer = str(binding.get("analysis_layer") or "")
                if layer not in SUBSTANTIVE_RESULT_LAYERS:
                    contract_errors.append(f"analysis coverage layer is invalid:{ref}")
                    continue
                for mismatch in _binding_plan_mismatches(binding, layer, plan_targets):
                    contract_errors.append(
                        f"analysis coverage result binding mismatch:{ref}:{mismatch}"
                    )
                planned_data_refs = set(plan_targets.get("data_evidence_refs") or [])
                actual_data_refs = set(card.get("result_data_evidence_refs") or [])
                if not actual_data_refs or not actual_data_refs.issubset(planned_data_refs):
                    contract_errors.append(
                        f"analysis coverage data evidence is outside the compiled plan:{ref}"
                    )

        all_refs = list(dict.fromkeys(
            support_refs + counter_refs + alternative_refs + robustness_refs
            + design_refs + coverage_result_refs
        ))
        evidence_errors = _evidence_errors(all_refs, evidence, finding_id)
        if selected_family:
            for ref in all_refs:
                card = evidence.get(ref)
                if card and card.get("verified") is True and card.get("family_id") != selected_family:
                    evidence_errors.append(f"{finding_id}.evidence_outside_selected_family:{ref}")
        actual_groups = {
            str(evidence[ref].get("independence_group"))
            for ref in support_refs
            if ref in evidence and evidence[ref].get("verified") is True
        }
        if declared_groups and set(declared_groups) != actual_groups:
            evidence_errors.append(f"{finding_id}.declared_independence_groups_do_not_match_supporting_evidence")
        if isinstance(reviewed_units, int):
            support_units = {
                str(evidence[ref].get("unit_id"))
                for ref in support_refs
                if ref in evidence and evidence[ref].get("verified") is True
            }
            if len(support_units) > reviewed_units:
                evidence_errors.append(f"{finding_id}.support_units_exceed_reviewed_units")

        counter_valid = counter_status != "not_completed"
        alternatives_valid = claim_level not in INFERENCE_LEVELS or bool(normalized_alternatives)
        robustness_completed = [item for item in normalized_robustness if item["status"] in {"passed", "mixed", "failed"}]
        robustness_supportive = any(item["status"] in {"passed", "mixed"} for item in robustness_completed)
        coverage_valid = bool(strategy and reviewed_units and actual_groups)
        decision_valid = bool(_text(row, "decision_relevance") and _text(row, "decision_delta") and _text(row, "baseline"))
        if any(item["status"] == "failed" for item in robustness_completed) and confidence == "high":
            contract_errors.append("high confidence is invalid when a declared robustness check failed")
        if claim_level == "mechanism_hypothesis" and confidence == "high":
            contract_errors.append("mechanism hypotheses cannot use high confidence without a causal design")

        contract_valid = not contract_errors
        evidence_valid = bool(support_refs) and not evidence_errors
        adopted = (
            proposed_status in ADOPT_VALUES
            and request["succeeded"]
            and not request_errors
            and scope_ready
            and contract_valid
            and evidence_valid
            and counter_valid
            and decision_valid
        )
        anchor_quality_eligible = (
            adopted
            and coverage_valid
            and alternatives_valid
            and robustness_supportive
        )
        anchor_eligible = (
            anchor_quality_eligible
            and analysis_plan is None
            and claim_level != "mechanism_hypothesis"
        )
        if not adopted and proposed_status in ADOPT_VALUES:
            reasons: list[str] = []
            if not request["succeeded"] or request_errors:
                reasons.append("request_not_succeeded")
            if not scope_ready:
                reasons.append("scope_not_analysis_ready")
            if contract_errors:
                reasons.append("contract_invalid")
            if evidence_errors or not support_refs:
                reasons.append("evidence_invalid")
            if not counter_valid:
                reasons.append("counterexample_search_incomplete")
            if not decision_valid:
                reasons.append("decision_link_incomplete")
            rejection_reason = ";".join(reasons) or "not_adopted"

        advanced_presentation = (
            _advanced_presentation(_text(row, "claim"))
            if claim_level in ADVANCED_CLAIM_LEVELS else None
        )
        compiled.append({
            "finding_id": finding_id,
            "contract_valid": contract_valid,
            "contract_errors": contract_errors,
            "evidence_valid": evidence_valid,
            "evidence_errors": evidence_errors,
            "adopted": adopted,
            "anchor_eligible": anchor_eligible,
            "rejection_reason": rejection_reason or None,
            "deep_quality": {
                "coverage_valid": coverage_valid,
                "counterexample_search_valid": counter_valid,
                "alternative_explanations_valid": alternatives_valid,
                "robustness_supportive": robustness_supportive,
                "decision_link_valid": decision_valid,
                "required_analysis_layers_ready": (
                    plan_required_layers_ready
                    if analysis_plan is not None else True
                ),
                "required_analysis_layers_executed": (
                    False if analysis_plan is not None and plan_required_result_layers else True
                ),
            },
            "finding": {
                "increment_candidate_id": _text(row, "increment_candidate_id") or None,
                "title": (
                    advanced_presentation["title"]
                    if advanced_presentation else _text(row, "title")
                ),
                "claim": _text(row, "claim"),
                "claim_level": claim_level,
                "claim_design": normalized_claim_design,
                "analysis_coverage_evidence_refs": coverage_result_refs,
                "analysis_unit": _text(row, "analysis_unit"),
                "decision_relevance": (
                    advanced_presentation["decision_relevance"]
                    if advanced_presentation else _text(row, "decision_relevance")
                ),
                "baseline": (
                    advanced_presentation["baseline"]
                    if advanced_presentation else _text(row, "baseline")
                ),
                "coverage": {
                    "strategy": strategy,
                    "eligible_units": eligible_units,
                    "reviewed_units": reviewed_units,
                    "independent_source_groups": sorted(actual_groups),
                    "limitations": limitations,
                },
                "supporting_evidence_refs": support_refs,
                "counterexample_search": {
                    "status": counter_status,
                    "description": counter_description,
                    "evidence_refs": counter_refs,
                },
                "alternative_explanations": normalized_alternatives,
                "robustness_checks": normalized_robustness,
                "boundaries": boundaries,
                "decision_delta": (
                    advanced_presentation["decision_delta"]
                    if advanced_presentation else _text(row, "decision_delta")
                ),
                "confidence": confidence,
            },
        })

    executed_result_layers: set[str] = set()
    for item in compiled:
        if not item["adopted"]:
            continue
        finding = item.get("finding") or {}
        claim_design = finding.get("claim_design") or {}
        result_refs = list(claim_design.get("result_evidence_refs") or [])
        result_refs.extend(finding.get("analysis_coverage_evidence_refs") or [])
        for ref in dict.fromkeys(result_refs):
            card = evidence.get(ref)
            binding = card.get("result_analysis_binding") if isinstance(card, dict) else None
            if (
                isinstance(card, dict)
                and card.get("verified") is True
                and card.get("lane") == "analysis_result"
                and card.get("result_binding_status") == "supported"
                and card.get("result_coverage_status") == "completed"
                and isinstance(binding, dict)
            ):
                layer = str(binding.get("analysis_layer") or "")
                if (
                    layer in SUBSTANTIVE_RESULT_LAYERS
                    and not _binding_plan_mismatches(binding, layer, plan_targets)
                ):
                    executed_result_layers.add(layer)

    required_result_layers_executed = (
        not plan_required_result_layers
        or set(plan_required_result_layers).issubset(executed_result_layers)
    )
    for item in compiled:
        finding = item.get("finding") or {}
        if analysis_plan is None:
            continue
        quality = item["deep_quality"]
        quality["required_analysis_layers_executed"] = required_result_layers_executed
        item["anchor_eligible"] = bool(
            item["adopted"]
            and quality["coverage_valid"]
            and quality["alternative_explanations_valid"]
            and quality["robustness_supportive"]
            and quality["required_analysis_layers_ready"]
            and quality["required_analysis_layers_executed"]
        )

    adopted_count = sum(1 for item in compiled if item["adopted"])
    anchor_count = sum(1 for item in compiled if item["anchor_eligible"])
    completion_status = "preliminary" if anchor_count else "partial" if adopted_count else "core_question_unanswered"
    return {
        "contract_version": "data-lens-finding-adoption-ledger/1.0",
        "decision_question": decision_question,
        "request": request,
        "request_errors": request_errors,
        "scope_gate": {
            "contract_version": scope_gate.get("contract_version"),
            "next_action": scope_gate.get("next_action"),
            "selected_family_id": selected_family,
            "selection": scope_gate.get("selection"),
            "deep_analysis_allowed": scope_gate.get("deep_analysis_allowed"),
        },
        "deep_analysis_plan": {
            "provided": analysis_plan is not None,
            "contract_version": verified_plan.get("contract_version") if verified_plan else None,
            "contract_status": verified_plan.get("contract_status") if verified_plan else None,
            "decision_question": verified_plan.get("decision_question") if verified_plan else None,
            "objective": verified_plan.get("objective") if verified_plan else None,
            "analysis_unit": verified_plan.get("analysis_unit") if verified_plan else None,
            "population": verified_plan.get("population") if verified_plan else None,
            "source_question_spec": copy.deepcopy(
                verified_plan.get("source_question_spec")
            ) if verified_plan else None,
            "recompiled": verified_plan is not None,
            "data_generating_process": copy.deepcopy(
                verified_plan.get("data_generating_process")
            ) if verified_plan else {},
            "claim_permissions": plan_permissions,
            "analysis_targets": plan_targets,
            "analysis_layers": plan_layers,
            "recommended_probes": copy.deepcopy(
                verified_plan.get("recommended_probes")
            ) if verified_plan else [],
            "summary": copy.deepcopy(verified_plan.get("summary")) if verified_plan else {},
            "required_layers": plan_required_layers,
            "required_layers_ready": plan_required_layers_ready if verified_plan else True,
            "required_result_layers": plan_required_result_layers,
            "executed_result_layers": sorted(executed_result_layers),
            "required_result_layers_executed": (
                required_result_layers_executed if verified_plan else True
            ),
        },
        "evidence_index": evidence,
        "candidates": compiled,
        "summary": {
            "candidate_count": len(compiled),
            "adopted_count": adopted_count,
            "anchor_finding_count": anchor_count,
            "core_question_answered": anchor_count > 0,
        },
        "completion_status": completion_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile semantic finding candidates through scope, contract, evidence, counterexample, alternative, and robustness gates.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--scope-gate", type=Path, required=True)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(
        parser,
        args.output,
        [args.candidates, args.evidence_cards, args.scope_gate, *([args.analysis_plan] if args.analysis_plan else [])],
    )
    ledger = compile_findings(
        load_json(args.candidates), load_json(args.evidence_cards), load_json(args.scope_gate),
        args.evidence_cards.parent,
        load_json(args.analysis_plan) if args.analysis_plan else None,
    )
    write_json(args.output, ledger)
    print(json.dumps({"output": str(args.output.resolve()), "summary": ledger["summary"], "completion_status": ledger["completion_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
