from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


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
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be an array")
        candidates = []
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
