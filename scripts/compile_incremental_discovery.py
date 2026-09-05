from __future__ import annotations

import argparse
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from compile_deep_findings import adapt_deep_evidence


LEGACY_CONTRACT_VERSION = "data-lens-incremental-discovery-candidates/0.1"
CONTRACT_VERSION = "data-lens-incremental-discovery-candidates/0.2"
LEDGER_VERSION = "data-lens-incremental-discovery-ledger/0.2"
BRIEF_VERSION = "data-lens-incremental-discovery-brief/0.1"
CAPTURE_MODES = {"pre_engine_first_pass", "external_raw_baseline"}
SEARCH_OPERATORS = {
    "causal_direction",
    "feedback_location",
    "analysis_level",
    "shared_carrier",
    "decision_objective",
    "stage_shift",
    "selection_process",
    "metric_role",
    "cost_transfer",
    "incentive_response",
}
DESIGN_TYPES = {
    "active_experiment",
    "natural_experiment",
    "historical_comparison",
    "holdout_review",
    "simulation",
}
SAFETY_STATUSES = {"safe", "requires_authorization", "prohibited"}
GRANULARITIES = {
    "tick",
    "intraday_1m",
    "intraday_5m",
    "intraday_15m",
    "intraday_30m",
    "intraday_60m",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
}


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _evidence_identity(
    refs: list[str], evidence: dict[str, dict[str, Any]]
) -> tuple[set[str], set[str], set[str]]:
    groups: set[str] = set()
    units: set[str] = set()
    exact_locations: set[str] = set()
    for ref in refs:
        card = evidence.get(ref) or {}
        if card.get("independence_group"):
            groups.add(str(card["independence_group"]))
        if card.get("unit_id"):
            units.add(str(card["unit_id"]))
        if card.get("source_sha256") and isinstance(card.get("locator"), dict):
            exact_locations.add(
                f'{str(card["source_sha256"]).lower()}:{_canonical(card["locator"])}'
            )
    return groups, units, exact_locations


def _text_list(value: Any, field: str, errors: list[str], *, required: bool = True) -> list[str]:
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


def compile_baseline(row: Any, evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {
            "snapshot": {},
            "contract_valid": False,
            "contract_errors": ["native_first_pass must be an object"],
            "evidence_valid": False,
            "evidence_errors": [],
            "adequacy": {},
            "adequate_for_augmentation": False,
        }
    snapshot = deepcopy(row)
    errors: list[str] = []
    for field in ("baseline_id", "core_problem", "mechanism", "decision"):
        if not _text(row, field):
            errors.append(f"native_first_pass.{field} is required")
    capture_mode = _text(row, "capture_mode")
    if capture_mode not in CAPTURE_MODES:
        errors.append("native_first_pass.capture_mode is invalid")
    if row.get("captured_before_engine") is not True:
        errors.append("native_first_pass.captured_before_engine must be true")
    refs = _text_list(row.get("evidence_refs"), "native_first_pass.evidence_refs", errors)
    alternatives = _text_list(
        row.get("competing_explanations"),
        "native_first_pass.competing_explanations",
        errors,
    )
    predictions = _text_list(row.get("predictions"), "native_first_pass.predictions", errors)
    retained_findings = _text_list(
        row.get("retained_findings"),
        "native_first_pass.retained_findings",
        errors,
    )
    unresolved = _text_list(
        row.get("unresolved_observations"),
        "native_first_pass.unresolved_observations",
        errors,
        required=False,
    )
    evidence_errors = _evidence_errors(refs, evidence, "native_first_pass.evidence_refs")
    adequacy = {
        "core_problem_specific": bool(_text(row, "core_problem")),
        "mechanism_present": bool(_text(row, "mechanism")),
        "competing_explanation_present": bool(alternatives),
        "prediction_present": bool(predictions),
        "retained_findings_present": bool(retained_findings),
        "decision_present": bool(_text(row, "decision")),
        "evidence_present": bool(refs) and not evidence_errors,
    }
    contract_valid = not errors
    evidence_valid = bool(refs) and not evidence_errors
    return {
        "snapshot": snapshot,
        "contract_valid": contract_valid,
        "contract_errors": errors,
        "evidence_valid": evidence_valid,
        "evidence_errors": evidence_errors,
        "adequacy": adequacy,
        "adequate_for_augmentation": contract_valid and evidence_valid and all(adequacy.values()),
        "normalized": {
            "baseline_id": _text(row, "baseline_id"),
            "capture_mode": capture_mode,
            "captured_before_engine": row.get("captured_before_engine") is True,
            "core_problem": _text(row, "core_problem"),
            "mechanism": _text(row, "mechanism"),
            "evidence_refs": refs,
            "competing_explanations": alternatives,
            "predictions": predictions,
            "retained_findings": retained_findings,
            "decision": _text(row, "decision"),
            "unresolved_observations": unresolved,
        },
    }


def compile_incremental_discovery(
    payload: Any,
    evidence_payload: Any,
    evidence_base_dir: Path | None = None,
    brief_payload: Any | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("incremental discovery candidates must be an object")
    candidate_contract_version = str(payload.get("contract_version") or "")
    if candidate_contract_version not in {LEGACY_CONTRACT_VERSION, CONTRACT_VERSION}:
        raise ValueError("unsupported incremental discovery candidate contract")
    executable_contract = candidate_contract_version == CONTRACT_VERSION
    decision_question = str(payload.get("decision_question") or "").strip()
    if not decision_question:
        raise ValueError("decision_question is required and must preserve the user's original request")
    if not isinstance(brief_payload, dict) or brief_payload.get("contract_version") != BRIEF_VERSION:
        raise ValueError("a prepared incremental discovery brief is required")
    evidence = adapt_deep_evidence(evidence_payload, evidence_base_dir)
    baseline = compile_baseline(payload.get("native_first_pass"), evidence)

    search = payload.get("search")
    search_errors: list[str] = []
    if not isinstance(search, dict):
        search = {}
        search_errors.append("search must be an object")
    if str(brief_payload.get("decision_question") or "").strip() != decision_question:
        search_errors.append("prepared brief decision_question differs from candidate input")
    if brief_payload.get("baseline", {}).get("snapshot") != baseline.get("snapshot"):
        search_errors.append("native_first_pass differs from prepared baseline brief")
    expected_mode = "adversarial_augmentation" if baseline["adequate_for_augmentation"] else "full_discovery"
    if brief_payload.get("recommended_mode") != expected_mode:
        search_errors.append("prepared brief mode is inconsistent with the current E0")
    candidate_generation_pass = _text(search, "candidate_generation_pass")
    if not candidate_generation_pass:
        search_errors.append("search.candidate_generation_pass is required")
    attempted = _text_list(search.get("operators_attempted"), "search.operators_attempted", search_errors)
    invalid_operators = sorted(set(attempted) - SEARCH_OPERATORS)
    if invalid_operators:
        search_errors.append(f"search.operators_attempted contains invalid values:{','.join(invalid_operators)}")
    if len(attempted) != len(set(attempted)):
        search_errors.append("search.operators_attempted must not contain duplicates")

    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("candidates must be an array")
    if len(rows) > 6:
        raise ValueError("incremental discovery accepts at most 6 candidates")

    seen_ids: set[str] = set()
    used_operators: set[str] = set()
    compiled: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"candidate {index} must be an object")
        candidate_id = _text(row, "candidate_id") or f"invalid-{index + 1}"
        errors: list[str] = []
        if not executable_contract:
            errors.append(
                "legacy candidate contract lacks a frozen executable binding and cannot enter measured review"
            )
        if candidate_id in seen_ids:
            errors.append("candidate_id is duplicated")
        seen_ids.add(candidate_id)
        for field in (
            "candidate_id",
            "claim",
            "core_mechanism",
            "shared_carrier",
            "unexplained_observation",
            "decision_delta",
        ):
            if not _text(row, field):
                errors.append(f"{field} is required")
        operator = _text(row, "source_operator")
        if operator not in SEARCH_OPERATORS:
            errors.append("source_operator is invalid")
        if operator not in attempted:
            errors.append("source_operator was not declared in search.operators_attempted")
        if operator in used_operators:
            errors.append("only one candidate is allowed per source_operator")
        used_operators.add(operator)

        structural = row.get("structural_change")
        if not isinstance(structural, dict):
            structural = {}
            errors.append("structural_change must be an object")
        dimension = _text(structural, "dimension")
        e0_assumption = _text(structural, "e0_assumption")
        e1_assumption = _text(structural, "e1_assumption")
        if dimension not in SEARCH_OPERATORS:
            errors.append("structural_change.dimension is invalid")
        if dimension and operator and dimension != operator:
            errors.append("structural_change.dimension must match source_operator")
        if not e0_assumption or not e1_assumption:
            errors.append("structural_change requires e0_assumption and e1_assumption")
        assumption_distinct = bool(e0_assumption and e1_assumption and _normalize(e0_assumption) != _normalize(e1_assumption))
        if e0_assumption and e1_assumption and not assumption_distinct:
            errors.append("structural_change does not change the baseline assumption")

        mechanism_steps = _text_list(row.get("mechanism_steps"), "mechanism_steps", errors)
        if mechanism_steps and len(mechanism_steps) < 2:
            errors.append("mechanism_steps must contain at least two steps")
        failure_conditions = _text_list(row.get("failure_conditions"), "failure_conditions", errors)
        generation_refs = _text_list(row.get("generation_evidence_refs"), "generation_evidence_refs", errors)
        holdout_refs = _text_list(
            row.get("holdout_evidence_refs"),
            "holdout_evidence_refs",
            errors,
            required=False,
        )
        baseline_refs = set(baseline.get("normalized", {}).get("evidence_refs") or [])
        overlap = sorted((set(generation_refs) | baseline_refs) & set(holdout_refs))
        if overlap:
            errors.append(f"E0/generation and holdout evidence must be disjoint:{','.join(overlap)}")
        generation_groups, generation_units, generation_locations = _evidence_identity(
            sorted(set(generation_refs) | baseline_refs), evidence
        )
        holdout_groups, holdout_units, holdout_locations = _evidence_identity(holdout_refs, evidence)
        group_overlap = sorted(generation_groups & holdout_groups)
        unit_overlap = sorted(generation_units & holdout_units)
        location_overlap = sorted(generation_locations & holdout_locations)
        if group_overlap:
            errors.append(
                "E0/generation and holdout evidence reuse independence groups:"
                + ",".join(group_overlap)
            )
        if unit_overlap:
            errors.append(
                "E0/generation and holdout evidence reuse units:" + ",".join(unit_overlap)
            )
        if location_overlap:
            errors.append("E0/generation and holdout evidence reuse the same source locator")
        evidence_errors = _evidence_errors(generation_refs + holdout_refs, evidence, f"candidates[{candidate_id}]")

        test = row.get("discriminating_test")
        if not isinstance(test, dict):
            test = {}
            errors.append("discriminating_test must be an object")
        for field in (
            "question",
            "target_mechanism",
            "comparison",
            "changed_variable",
            "measurement_window",
            "e0_prediction",
            "e1_prediction",
            "distinguishing_observation",
            "invalidation_condition",
        ):
            if not _text(test, field):
                errors.append(f"discriminating_test.{field} is required")
        design_type = _text(test, "design_type")
        directness = _text(test, "directness")
        safety_status = _text(test, "safety_status")
        if design_type not in DESIGN_TYPES:
            errors.append("discriminating_test.design_type is invalid")
        if directness not in {"direct", "partial"}:
            errors.append("discriminating_test.directness is invalid")
        if safety_status not in SAFETY_STATUSES:
            errors.append("discriminating_test.safety_status is invalid")
        if safety_status == "prohibited":
            errors.append("a prohibited test cannot qualify an incremental candidate")
        e0_prediction = _text(test, "e0_prediction")
        e1_prediction = _text(test, "e1_prediction")
        core_mechanism = _text(row, "core_mechanism")
        target_mechanism = _text(test, "target_mechanism")
        mechanism_target_bound = bool(
            core_mechanism
            and target_mechanism
            and _normalize(core_mechanism) == _normalize(target_mechanism)
        )
        if core_mechanism and target_mechanism and not mechanism_target_bound:
            errors.append("discriminating_test.target_mechanism must match candidate core_mechanism")
        prediction_distinct = bool(e0_prediction and e1_prediction and _normalize(e0_prediction) != _normalize(e1_prediction))
        if e0_prediction and e1_prediction and not prediction_distinct:
            errors.append("discriminating_test predictions are not different")
        if directness == "partial":
            errors.append("discriminating_test must directly distinguish E0 from E1")

        execution = test.get("execution_binding")
        if not isinstance(execution, dict):
            execution = {}
            if executable_contract:
                errors.append("discriminating_test.execution_binding must be an object")
        mechanism_variable = _text(execution, "mechanism_variable")
        required_granularity = _text(execution, "required_granularity")
        evaluation_window = execution.get("evaluation_window")
        measurement = execution.get("measurement")
        e0_predicate = execution.get("e0_predicate")
        e1_predicate = execution.get("e1_predicate")
        data_evidence_refs = _text_list(
            execution.get("data_evidence_refs", []),
            "discriminating_test.execution_binding.data_evidence_refs",
            errors,
            required=False,
        )
        if executable_contract:
            if not mechanism_variable:
                errors.append("discriminating_test.execution_binding.mechanism_variable is required")
            elif _normalize(mechanism_variable) != _normalize(_text(test, "changed_variable")):
                errors.append("execution mechanism_variable must match discriminating_test.changed_variable")
            if required_granularity not in GRANULARITIES:
                errors.append("discriminating_test.execution_binding.required_granularity is invalid")
            if not isinstance(evaluation_window, dict) or not _text(evaluation_window, "start") or not _text(evaluation_window, "end"):
                errors.append("discriminating_test.execution_binding.evaluation_window requires start and end")
            if not isinstance(measurement, dict) or not _text(measurement, "kind"):
                errors.append("discriminating_test.execution_binding.measurement requires kind")
            if not isinstance(e0_predicate, dict) or not _text(e0_predicate, "operator"):
                errors.append("discriminating_test.execution_binding.e0_predicate requires operator")
            if not isinstance(e1_predicate, dict) or not _text(e1_predicate, "operator"):
                errors.append("discriminating_test.execution_binding.e1_predicate requires operator")
            if isinstance(e0_predicate, dict) and isinstance(e1_predicate, dict) and _canonical(e0_predicate) == _canonical(e1_predicate):
                errors.append("executable E0 and E1 predicates must differ")
            outside_holdout = sorted(set(data_evidence_refs) - set(holdout_refs))
            if outside_holdout:
                errors.append(
                    "execution data evidence must come from declared holdout evidence:"
                    + ",".join(outside_holdout)
                )

        contract_valid = not errors
        evidence_valid = bool(generation_refs) and not evidence_errors
        mechanically_distinct = (
            assumption_distinct
            and prediction_distinct
            and mechanism_target_bound
            and directness == "direct"
        )
        eligible_for_review = (
            baseline["adequate_for_augmentation"]
            and not search_errors
            and contract_valid
            and evidence_valid
            and mechanically_distinct
            and executable_contract
        )
        compiled.append({
            "candidate_id": candidate_id,
            "contract_valid": contract_valid,
            "contract_errors": errors,
            "evidence_valid": evidence_valid,
            "evidence_errors": evidence_errors,
            "mechanically_distinct": mechanically_distinct,
            "eligible_for_review": eligible_for_review,
            "candidate": {
                "source_operator": operator,
                "claim": _text(row, "claim"),
                "core_mechanism": core_mechanism,
                "structural_change": {
                    "dimension": dimension,
                    "e0_assumption": e0_assumption,
                    "e1_assumption": e1_assumption,
                },
                "shared_carrier": _text(row, "shared_carrier"),
                "mechanism_steps": mechanism_steps,
                "unexplained_observation": _text(row, "unexplained_observation"),
                "generation_evidence_refs": generation_refs,
                "holdout_evidence_refs": holdout_refs,
                "discriminating_test": {
                    "question": _text(test, "question"),
                    "target_mechanism": target_mechanism,
                    "design_type": design_type,
                    "comparison": _text(test, "comparison"),
                    "changed_variable": _text(test, "changed_variable"),
                    "measurement_window": _text(test, "measurement_window"),
                    "e0_prediction": e0_prediction,
                    "e1_prediction": e1_prediction,
                    "distinguishing_observation": _text(test, "distinguishing_observation"),
                    "invalidation_condition": _text(test, "invalidation_condition"),
                    "directness": directness,
                    "safety_status": safety_status,
                    "execution_binding": {
                        "mechanism_variable": mechanism_variable,
                        "data_evidence_refs": data_evidence_refs,
                        "required_granularity": required_granularity,
                        "evaluation_window": evaluation_window,
                        "measurement": measurement,
                        "e0_predicate": e0_predicate,
                        "e1_predicate": e1_predicate,
                    },
                },
                "decision_delta": _text(row, "decision_delta"),
                "failure_conditions": failure_conditions,
            },
        })

    max_review_candidates = int(
        (brief_payload.get("generation_brief") or {}).get("max_review_candidates", 0)
    )
    eligible_seen = 0
    for item in compiled:
        if not item["eligible_for_review"]:
            continue
        eligible_seen += 1
        if eligible_seen > max_review_candidates:
            item["eligible_for_review"] = False
            item["contract_valid"] = False
            item["contract_errors"].append(
                "adversarial augmentation review budget exceeded; rank and retain at most two candidates"
            )
    eligible_count = sum(1 for item in compiled if item["eligible_for_review"])
    if not baseline["adequate_for_augmentation"]:
        recommended_mode = "full_discovery"
        provisional_result = "baseline_incomplete"
    else:
        recommended_mode = "adversarial_augmentation"
        provisional_result = "candidates_ready_for_review" if eligible_count else "no_increment_detected"
    return {
        "contract_version": LEDGER_VERSION,
        "decision_question": decision_question,
        "baseline": baseline,
        "search": {
            "candidate_generation_pass": candidate_generation_pass,
            "operators_attempted": attempted,
            "contract_valid": not search_errors,
            "contract_errors": search_errors,
            "recommended_mode": recommended_mode,
            "candidate_contract_version": candidate_contract_version,
        },
        "evidence_index": evidence,
        "candidates": compiled,
        "summary": {
            "candidate_count": len(compiled),
            "eligible_for_review_count": eligible_count,
            "provisional_result": provisional_result,
            "analysis_increment_claimed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile E0 and structurally different E1 candidates without claiming analysis increment."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.candidates, args.brief, args.evidence_cards])
    ledger = compile_incremental_discovery(
        load_json(args.candidates),
        load_json(args.evidence_cards),
        args.evidence_cards.parent,
        load_json(args.brief),
    )
    write_json(args.output, ledger)
    print(json.dumps({"output": str(args.output.resolve()), "summary": ledger["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
