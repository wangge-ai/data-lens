from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import (
    guard_cli_output,
    has_explicit_action_directive,
    has_explicit_causal_wording,
    has_explicit_prediction_wording,
    has_hypothesis_qualifier,
    has_noncausal_relation_wording,
    load_json,
    write_json,
)
from compile_deep_findings import adapt_deep_evidence, _binding_plan_mismatches


ADVANCED_CLAIM_PERMISSIONS = {
    "prediction": "predictive",
    "causal_effect": "causal",
    "decision_rule": "decision",
}
SUBSTANTIVE_RESULT_LAYERS = {"heterogeneity", "mechanism", "causal", "predictive", "decision"}
ADVANCED_VALIDATION_TYPES = {
    "prediction": {"out_of_sample"},
    "causal_effect": {"randomized_experiment", "identified_observational_estimate"},
    "decision_rule": {"decision_analysis", "policy_evaluation"},
}
ADVANCED_DECISION_RELEVANCE = "该结果只回答已编译的分析目标，并按其证据层级进入决策。"
ADVANCED_BASELINE = "以编译后的分析目标、实际测量和设计边界为准。"
ADVANCED_DECISION_DELTA = "只在冻结的目标、方法、验证设计与失效条件内使用；超出边界须重新评估。"
PLAN_INTEGRITY_FIELDS = (
    "contract_version", "contract_status", "decision_question", "objective",
    "analysis_unit", "population", "data_generating_process", "analysis_targets",
    "analysis_layers", "claim_permissions", "recommended_probes", "summary",
)


def _rebuild_evidence_cards(evidence: dict[str, Any]) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    passthrough = (
        "claim", "source", "source_sha256", "locator", "verified", "unit_id",
        "independence_group", "family_id", "lane", "directness", "design_binding",
        "identification_check_binding",
        "result_contract_version", "result_status", "caveat", "status",
    )
    for evidence_id, card in evidence.items():
        if not isinstance(card, dict):
            continue
        rebuilt = {"id": evidence_id}
        rebuilt.update({key: card.get(key) for key in passthrough if card.get(key) is not None})
        cards.append(rebuilt)
    return {"contract_version": "data-lens-deep-evidence-cards/1.0", "cards": cards}


def validate(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["ledger must be an object"]
    errors: list[str] = []
    if payload.get("contract_version") != "data-lens-finding-adoption-ledger/1.0":
        errors.append("unsupported finding adoption ledger contract")
    if not str(payload.get("decision_question") or "").strip():
        errors.append("decision_question is required")
    request = payload.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("succeeded"), bool):
        errors.append("request.succeeded must be boolean")
        request = {"succeeded": False}
    scope = payload.get("scope_gate")
    if not isinstance(scope, dict):
        errors.append("scope_gate must be an object")
        scope = {}
    evidence = payload.get("evidence_index")
    if not isinstance(evidence, dict):
        errors.append("evidence_index must be an object")
        evidence = {}
    else:
        recorded_evidence = evidence
        try:
            refreshed_evidence = adapt_deep_evidence(
                _rebuild_evidence_cards(recorded_evidence)
            )
            if set(refreshed_evidence) != set(recorded_evidence):
                errors.append("evidence_index ids differ from fresh verification")
            integrity_fields = (
                "verified", "verification_errors", "source", "source_sha256", "locator",
                "result_contract_version", "result_status", "result_decision_question",
                "result_analysis_binding", "result_binding_status", "result_coverage_status",
                "result_bound_statement", "result_bound_measurement", "result_bound_claim",
                "result_data_evidence_refs", "result_data_sha256", "result_source_spec",
            )
            for evidence_id, refreshed in refreshed_evidence.items():
                recorded = recorded_evidence.get(evidence_id)
                if not isinstance(recorded, dict):
                    continue
                for field in integrity_fields:
                    if recorded.get(field) != refreshed.get(field):
                        errors.append(
                            f"evidence_index.{evidence_id}.{field} differs from fresh verification"
                        )
            evidence = refreshed_evidence
        except (ValueError, TypeError, OSError) as exc:
            errors.append(f"evidence_index fresh verification failed:{exc}")
            evidence = {}
    analysis_plan = payload.get("deep_analysis_plan")
    # Ledgers created before deep-analysis-plan/0.1 remain valid for ordinary
    # descriptive and mechanism-hypothesis findings.  A plan becomes mandatory
    # only when an advanced claim is actually present.
    if analysis_plan is None:
        analysis_plan = {"provided": False, "claim_permissions": {}}
    elif not isinstance(analysis_plan, dict):
        errors.append("deep_analysis_plan must be an object")
        analysis_plan = {"provided": False, "claim_permissions": {}}
    plan_provided = analysis_plan.get("provided") is True
    if plan_provided and analysis_plan.get("contract_version") != "data-lens-deep-analysis-plan/0.1":
        errors.append("deep_analysis_plan.contract_version is invalid")
    if plan_provided:
        source_spec = analysis_plan.get("source_question_spec")
        if not isinstance(source_spec, dict):
            errors.append("deep_analysis_plan.source_question_spec is required")
        else:
            try:
                from compile_deep_analysis_question import compile_deep_analysis_question

                recompiled = compile_deep_analysis_question(
                    source_spec, _rebuild_evidence_cards(evidence)
                )
                if recompiled.get("contract_status") != "compiled":
                    errors.append("deep_analysis_plan source question no longer compiles")
                for field in PLAN_INTEGRITY_FIELDS:
                    if analysis_plan.get(field) != recompiled.get(field):
                        errors.append(f"deep_analysis_plan.{field} differs from fresh compilation")
                expected_required = list((recompiled.get("summary") or {}).get("required_layers") or [])
                if analysis_plan.get("required_layers") != expected_required:
                    errors.append("deep_analysis_plan.required_layers differs from fresh compilation")
                expected_ready = bool(expected_required) and all(
                    (recompiled.get("analysis_layers") or {}).get(layer, {}).get("status") == "ready"
                    for layer in expected_required
                )
                if analysis_plan.get("required_layers_ready") is not expected_ready:
                    errors.append("deep_analysis_plan.required_layers_ready is invalid")
                if analysis_plan.get("recompiled") is not True:
                    errors.append("deep_analysis_plan.recompiled must be true")
            except (ValueError, TypeError) as exc:
                errors.append(f"deep_analysis_plan recompile failed:{exc}")
    plan_permissions = analysis_plan.get("claim_permissions") or {}
    if not isinstance(plan_permissions, dict):
        errors.append("deep_analysis_plan.claim_permissions must be an object")
        plan_permissions = {}
    plan_targets = analysis_plan.get("analysis_targets") or {}
    if plan_provided and not isinstance(plan_targets, dict):
        errors.append("deep_analysis_plan.analysis_targets must be an object")
        plan_targets = {}
    plan_required_layers = list(analysis_plan.get("required_layers") or [])
    plan_required_result_layers = [
        layer for layer in plan_required_layers
        if layer in SUBSTANTIVE_RESULT_LAYERS
    ]
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be an array")
        candidates = []
    executed_result_layers: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("adopted") is not True:
            continue
        finding = candidate.get("finding")
        claim_design = finding.get("claim_design") if isinstance(finding, dict) else None
        refs = list(claim_design.get("result_evidence_refs") or []) if isinstance(claim_design, dict) else []
        if isinstance(finding, dict):
            refs.extend(finding.get("analysis_coverage_evidence_refs") or [])
        for ref in dict.fromkeys(refs):
            card = evidence.get(ref)
            binding = card.get("result_analysis_binding") if isinstance(card, dict) else None
            if (
                isinstance(card, dict)
                and card.get("verified") is True
                and card.get("lane") == "analysis_result"
                and card.get("result_binding_status") == "supported"
                and card.get("result_coverage_status") == "completed"
                and isinstance(binding, dict)
                and binding.get("analysis_layer") in SUBSTANTIVE_RESULT_LAYERS
                and not _binding_plan_mismatches(
                    binding, str(binding.get("analysis_layer") or ""), plan_targets
                )
            ):
                executed_result_layers.add(binding["analysis_layer"])
    required_result_layers_executed = (
        not plan_required_result_layers
        or set(plan_required_result_layers).issubset(executed_result_layers)
    )
    if plan_provided:
        if analysis_plan.get("required_result_layers") != plan_required_result_layers:
            errors.append("deep_analysis_plan.required_result_layers is invalid")
        if analysis_plan.get("executed_result_layers") != sorted(executed_result_layers):
            errors.append("deep_analysis_plan.executed_result_layers is invalid")
        if analysis_plan.get("required_result_layers_executed") is not required_result_layers_executed:
            errors.append("deep_analysis_plan.required_result_layers_executed is invalid")
    seen: set[str] = set()
    adopted_count = 0
    anchor_count = 0
    for index, candidate in enumerate(candidates):
        prefix = f"candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{prefix} must be an object")
            continue
        finding_id = candidate.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            errors.append(f"{prefix}.finding_id is required")
        elif finding_id in seen:
            errors.append(f"{prefix}.finding_id is duplicated")
        else:
            seen.add(finding_id)
        for field in ("contract_valid", "evidence_valid", "adopted", "anchor_eligible"):
            if not isinstance(candidate.get(field), bool):
                errors.append(f"{prefix}.{field} must be boolean")
        quality = candidate.get("deep_quality")
        if not isinstance(quality, dict):
            errors.append(f"{prefix}.deep_quality must be an object")
            quality = {}
        for field in (
            "coverage_valid",
            "counterexample_search_valid",
            "alternative_explanations_valid",
            "robustness_supportive",
            "decision_link_valid",
        ):
            if not isinstance(quality.get(field), bool):
                errors.append(f"{prefix}.deep_quality.{field} must be boolean")
        finding = candidate.get("finding")
        if not isinstance(finding, dict):
            errors.append(f"{prefix}.finding must be an object")
            finding = {}
        claim_level = str(finding.get("claim_level") or "")
        coverage_result_refs = finding.get("analysis_coverage_evidence_refs")
        if not isinstance(coverage_result_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in coverage_result_refs
        ):
            errors.append(f"{prefix}.analysis_coverage_evidence_refs_must_be_string_array")
            coverage_result_refs = []
        for ref in coverage_result_refs:
            card = evidence.get(ref)
            if not isinstance(card, dict):
                continue
            binding = card.get("result_analysis_binding")
            if card.get("lane") != "analysis_result" or card.get("directness") != "derived":
                errors.append(f"{prefix}.analysis_coverage_not_analysis_output:{ref}")
            if card.get("result_decision_question") != payload.get("decision_question"):
                errors.append(f"{prefix}.analysis_coverage_question_mismatch:{ref}")
            if (
                not isinstance(binding, dict)
                or card.get("result_binding_status") != "supported"
                or card.get("result_coverage_status") != "completed"
            ):
                errors.append(f"{prefix}.analysis_coverage_not_completed:{ref}")
                continue
            layer = str(binding.get("analysis_layer") or "")
            if layer not in SUBSTANTIVE_RESULT_LAYERS:
                errors.append(f"{prefix}.analysis_coverage_layer_invalid:{ref}")
                continue
            for mismatch in _binding_plan_mismatches(binding, layer, plan_targets):
                errors.append(f"{prefix}.analysis_coverage_binding_mismatch:{ref}:{mismatch}")
            planned_data_refs = set(plan_targets.get("data_evidence_refs") or [])
            actual_data_refs = set(card.get("result_data_evidence_refs") or [])
            if not actual_data_refs or not actual_data_refs.issubset(planned_data_refs):
                errors.append(f"{prefix}.analysis_coverage_data_evidence_mismatch:{ref}")
        permission_family = ADVANCED_CLAIM_PERMISSIONS.get(claim_level)
        published_wording = "\n".join(
            str(finding.get(field) or "")
            for field in ("title", "claim", "decision_relevance", "baseline", "decision_delta")
        )
        if candidate.get("contract_valid") is True or candidate.get("adopted") is True or candidate.get("anchor_eligible") is True:
            if claim_level != "causal_effect" and has_explicit_causal_wording(published_wording):
                if claim_level != "mechanism_hypothesis" or not has_hypothesis_qualifier(published_wording):
                    errors.append(f"{prefix}.explicit_causal_wording_requires_causal_effect")
            if claim_level != "prediction" and has_explicit_prediction_wording(published_wording):
                errors.append(f"{prefix}.explicit_prediction_requires_prediction_evidence")
            if claim_level != "decision_rule" and has_explicit_action_directive(published_wording):
                errors.append(f"{prefix}.action_directive_requires_decision_rule_evidence")
            if claim_level == "relationship" and not has_noncausal_relation_wording(published_wording):
                errors.append(f"{prefix}.relationship_wording_must_be_noncausal")
        if plan_provided:
            if not isinstance(quality.get("required_analysis_layers_ready"), bool):
                errors.append(f"{prefix}.deep_quality.required_analysis_layers_ready must be boolean")
            elif quality.get("required_analysis_layers_ready") is not analysis_plan.get("required_layers_ready"):
                errors.append(f"{prefix}.deep_quality.required_analysis_layers_ready is invalid")
            if not isinstance(quality.get("required_analysis_layers_executed"), bool):
                errors.append(f"{prefix}.deep_quality.required_analysis_layers_executed must be boolean")
            elif quality.get("required_analysis_layers_executed") is not required_result_layers_executed:
                errors.append(f"{prefix}.deep_quality.required_analysis_layers_executed is invalid")
        if permission_family:
            if finding.get("title") != finding.get("claim"):
                errors.append(f"{prefix}.advanced_title_must_equal_measured_claim")
            if finding.get("decision_relevance") != ADVANCED_DECISION_RELEVANCE:
                errors.append(f"{prefix}.advanced_decision_relevance_is_not_canonical")
            if finding.get("baseline") != ADVANCED_BASELINE:
                errors.append(f"{prefix}.advanced_baseline_is_not_canonical")
            if finding.get("decision_delta") != ADVANCED_DECISION_DELTA:
                errors.append(f"{prefix}.advanced_decision_delta_is_not_canonical")
            if not plan_provided:
                errors.append(f"{prefix}.advanced_claim_without_analysis_plan")
            if plan_permissions.get(permission_family) != "allowed":
                errors.append(f"{prefix}.advanced_claim_not_allowed:{permission_family}")
            claim_design = finding.get("claim_design")
            if not isinstance(claim_design, dict):
                errors.append(f"{prefix}.advanced_claim_requires_claim_design")
                claim_design = {}
            if not str(claim_design.get("target") or "").strip() or not str(claim_design.get("method") or "").strip():
                errors.append(f"{prefix}.claim_design_target_and_method_required")
            assumptions = claim_design.get("assumptions")
            if not isinstance(assumptions, list) or not assumptions or not all(
                isinstance(item, str) and item.strip() for item in assumptions
            ):
                errors.append(f"{prefix}.claim_design_assumptions_required")
            result_refs = claim_design.get("result_evidence_refs")
            if not isinstance(result_refs, list) or not result_refs or not all(
                isinstance(item, str) and item.strip() for item in result_refs
            ):
                errors.append(f"{prefix}.claim_design_result_evidence_required")
            if claim_design.get("analysis_layer") != permission_family:
                errors.append(f"{prefix}.claim_design_layer_mismatch")
            expected_target = (plan_targets.get(permission_family) or {}).get("target") if isinstance(plan_targets, dict) else None
            if not isinstance(expected_target, str) or not expected_target.strip() or claim_design.get("target") != expected_target:
                errors.append(f"{prefix}.claim_design_target_mismatch")
            if claim_design.get("validation_type") not in ADVANCED_VALIDATION_TYPES.get(claim_level, set()):
                errors.append(f"{prefix}.claim_design_validation_type_mismatch")
            if claim_design.get("validation_status") != "supported":
                errors.append(f"{prefix}.advanced_claim_validation_not_supported")
            for ref in claim_design.get("result_evidence_refs") or []:
                card = evidence.get(ref)
                if isinstance(card, dict) and (
                    card.get("lane") != "analysis_result" or card.get("directness") != "derived"
                ):
                    errors.append(f"{prefix}.claim_design_result_not_analysis_output:{ref}")
                elif isinstance(card, dict) and (
                    not card.get("result_contract_version")
                    or card.get("result_status") not in {"completed", "succeeded"}
                ):
                    errors.append(f"{prefix}.claim_design_result_contract_missing:{ref}")
                elif isinstance(card, dict) and card.get("result_decision_question") != payload.get("decision_question"):
                    errors.append(f"{prefix}.claim_design_result_question_mismatch:{ref}")
                if isinstance(card, dict):
                    binding = card.get("result_analysis_binding")
                    if not isinstance(binding, dict) or card.get("result_binding_status") != "supported":
                        errors.append(f"{prefix}.claim_design_result_binding_invalid:{ref}")
                    else:
                        for key, expected in (
                            ("analysis_layer", claim_design.get("analysis_layer")),
                            ("target", claim_design.get("target")),
                            ("validation_type", claim_design.get("validation_type")),
                            ("method", claim_design.get("method")),
                        ):
                            if binding.get(key) != expected:
                                errors.append(f"{prefix}.claim_design_result_binding_mismatch:{ref}:{key}")
                        for mismatch in _binding_plan_mismatches(
                            binding, str(claim_design.get("analysis_layer") or ""), plan_targets
                        ):
                            errors.append(
                                f"{prefix}.claim_design_result_binding_mismatch:{ref}:{mismatch}"
                            )
                        if finding.get("claim") != card.get("result_bound_claim"):
                            errors.append(f"{prefix}.claim_does_not_match_measured_result:{ref}")
                        plan_target = plan_targets.get(permission_family) if isinstance(plan_targets, dict) else None
                        planned_data_refs = set(plan_targets.get("data_evidence_refs") or [])
                        actual_data_refs = set(card.get("result_data_evidence_refs") or [])
                        if not actual_data_refs or not actual_data_refs.issubset(planned_data_refs):
                            errors.append(f"{prefix}.claim_design_result_data_evidence_mismatch:{ref}")
                        if permission_family == "causal" and binding.get("identification_strategy") != (
                            plan_target.get("identification_strategy") if isinstance(plan_target, dict) else None
                        ):
                            errors.append(f"{prefix}.claim_design_result_identification_mismatch:{ref}")
                        if permission_family == "causal" and isinstance(plan_target, dict) and (
                            claim_design.get("method") != plan_target.get("planned_method")
                        ):
                            errors.append(f"{prefix}.claim_design_result_estimator_mismatch:{ref}")
                        if permission_family == "causal" and isinstance(plan_target, dict):
                            for key in (
                                "intervention", "comparator", "outcome_field", "group_field",
                                "intervention_value", "comparator_value",
                            ):
                                if binding.get(key) != plan_target.get(key):
                                    errors.append(f"{prefix}.claim_design_result_{key}_mismatch:{ref}")
                            if sorted(binding.get("design_evidence_refs") or []) != sorted(
                                plan_target.get("design_evidence_refs") or []
                            ):
                                errors.append(f"{prefix}.claim_design_result_design_evidence_mismatch:{ref}")
                        if permission_family == "predictive" and isinstance(plan_target, dict):
                            if binding.get("validation_design") != plan_target.get("validation"):
                                errors.append(f"{prefix}.claim_design_result_validation_mismatch:{ref}")
                            if binding.get("outcome_field") != plan_target.get("outcome_field"):
                                errors.append(f"{prefix}.claim_design_result_outcome_field_mismatch:{ref}")
                            for key in (
                                "horizon", "horizon_steps", "horizon_unit", "cutoff", "metric",
                                "baseline_model", "baseline_kind", "cutoff_mode",
                            ):
                                if binding.get(key) != plan_target.get(key):
                                    errors.append(f"{prefix}.claim_design_result_{key}_mismatch:{ref}")
                        if permission_family == "decision" and isinstance(plan_target, dict):
                            if binding.get("evidence_basis") != plan_target.get("evidence_basis"):
                                errors.append(f"{prefix}.claim_design_result_basis_mismatch:{ref}")
                            if binding.get("decision_threshold") != plan_target.get("decision_threshold"):
                                errors.append(f"{prefix}.claim_design_result_threshold_mismatch:{ref}")
                            if binding.get("utility_metric") != plan_target.get("utility_metric"):
                                errors.append(f"{prefix}.claim_design_result_utility_mismatch:{ref}")
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
                if claim_design.get("validation_type") != expected_validation:
                    errors.append(f"{prefix}.claim_design_identification_validation_mismatch")
        refs: list[str] = []
        refs.extend(finding.get("supporting_evidence_refs") or [])
        refs.extend((finding.get("counterexample_search") or {}).get("evidence_refs") or [])
        for alternative in finding.get("alternative_explanations") or []:
            if isinstance(alternative, dict):
                refs.extend(alternative.get("evidence_refs") or [])
                refs.extend(alternative.get("discriminating_evidence_refs") or [])
        for check in finding.get("robustness_checks") or []:
            if isinstance(check, dict):
                refs.extend(check.get("evidence_refs") or [])
        if isinstance(finding.get("claim_design"), dict):
            refs.extend(finding["claim_design"].get("result_evidence_refs") or [])
        refs.extend(finding.get("analysis_coverage_evidence_refs") or [])
        for ref in refs:
            if ref not in evidence:
                errors.append(f"{prefix}.unknown_evidence_reference:{ref}")
            elif (candidate.get("evidence_valid") is True or candidate.get("adopted") is True) and evidence[ref].get("verified") is not True:
                errors.append(f"{prefix}.invalid_verified_evidence_reference:{ref}")
        if candidate.get("adopted"):
            adopted_count += 1
            if request.get("succeeded") is not True:
                errors.append(f"{prefix}.adopted_when_request_failed")
            if scope.get("deep_analysis_allowed") is not True or scope.get("next_action") != "analysis_ready":
                errors.append(f"{prefix}.adopted_without_analysis_ready_scope")
            if candidate.get("contract_valid") is not True or candidate.get("evidence_valid") is not True:
                errors.append(f"{prefix}.adopted_before_contract_or_evidence_validation")
            if quality.get("counterexample_search_valid") is not True or quality.get("decision_link_valid") is not True:
                errors.append(f"{prefix}.adopted_without_counterexample_or_decision_gate")
        elif not candidate.get("rejection_reason"):
            errors.append(f"{prefix}.non_adopted_requires_rejection_reason")
        if candidate.get("anchor_eligible"):
            anchor_count += 1
            if candidate.get("adopted") is not True:
                errors.append(f"{prefix}.anchor_must_be_adopted")
            for field in (
                "coverage_valid",
                "counterexample_search_valid",
                "alternative_explanations_valid",
                "robustness_supportive",
                "decision_link_valid",
            ):
                if quality.get(field) is not True:
                    errors.append(f"{prefix}.anchor_quality_gate_failed:{field}")
            if plan_provided and quality.get("required_analysis_layers_ready") is not True:
                errors.append(
                    f"{prefix}.anchor_quality_gate_failed:required_analysis_layers_ready"
                )
            if plan_provided and quality.get("required_analysis_layers_executed") is not True:
                errors.append(
                    f"{prefix}.anchor_quality_gate_failed:required_analysis_layers_executed"
                )
            if claim_level == "mechanism_hypothesis" and not plan_provided:
                errors.append(
                    f"{prefix}.mechanism_anchor_requires_compiled_plan_and_executed_result"
                )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
        summary = {}
    expected = {
        "candidate_count": len(candidates),
        "adopted_count": adopted_count,
        "anchor_finding_count": anchor_count,
        "core_question_answered": anchor_count > 0,
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            errors.append(f"summary.{field} does not match ledger contents")
    completion = payload.get("completion_status")
    expected_completion = "preliminary" if anchor_count else "partial" if adopted_count else "core_question_unanswered"
    if completion != expected_completion:
        errors.append(f"completion_status must be {expected_completion}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an evidence-gated deep finding adoption ledger.")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        guard_cli_output(parser, args.output, [args.ledger])
    errors = validate(load_json(args.ledger))
    result = {"valid": not errors, "errors": errors}
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
