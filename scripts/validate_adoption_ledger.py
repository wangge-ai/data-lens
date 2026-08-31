from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


def validate(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["ledger must be a JSON object"]
    if payload.get("contract_version") != "data-lens-adoption-ledger/1.0":
        errors.append("contract_version must be data-lens-adoption-ledger/1.0")
    request = payload.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("succeeded"), bool):
        errors.append("request.succeeded must be boolean")
        request = {"succeeded": False}
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
    for index, candidate in enumerate(candidates):
        prefix = f"candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{prefix} must be an object")
            continue
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            errors.append(f"{prefix}.candidate_id is required")
        elif candidate_id in seen:
            errors.append(f"{prefix}.candidate_id is duplicated")
        else:
            seen.add(candidate_id)
        for field in ("contract_valid", "evidence_valid", "adopted"):
            if not isinstance(candidate.get(field), bool):
                errors.append(f"{prefix}.{field} must be boolean")
        refs = candidate.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append(f"{prefix}.evidence_refs must be an array")
            refs = []
        verified_refs = [ref for ref in refs if isinstance(evidence.get(ref), dict) and evidence[ref].get("verified") is True]
        if candidate.get("evidence_valid") and not verified_refs:
            errors.append(f"{prefix} marks evidence valid without a verified evidence reference")
        if candidate.get("adopted"):
            adopted_count += 1
            if not request.get("succeeded"):
                errors.append(f"{prefix} cannot be adopted when the request failed")
            if candidate.get("contract_valid") is not True:
                errors.append(f"{prefix} cannot be adopted before contract validation")
            if candidate.get("evidence_valid") is not True:
                errors.append(f"{prefix} cannot be adopted before evidence validation")
            if not verified_refs:
                errors.append(f"{prefix} cannot be adopted without verified evidence")
        elif not candidate.get("rejection_reason"):
            errors.append(f"{prefix} is not adopted and must record rejection_reason")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
        summary = {}
    if summary.get("candidate_count") != len(candidates):
        errors.append("summary.candidate_count does not match candidates")
    if summary.get("adopted_count") != adopted_count:
        errors.append("summary.adopted_count does not match adopted candidates")
    core_answered = summary.get("core_question_answered")
    if not isinstance(core_answered, bool):
        errors.append("summary.core_question_answered must be boolean")
        core_answered = False
    completion = payload.get("completion_status")
    allowed_completion = {"complete", "preliminary", "partial", "core_question_unanswered"}
    if completion not in allowed_completion:
        errors.append("completion_status is invalid")
    if completion == "complete" and (not core_answered or adopted_count < 1):
        errors.append("complete requires the core question to be answered by at least one adopted finding")
    if not core_answered and completion != "core_question_unanswered":
        errors.append("an unanswered core question requires completion_status=core_question_unanswered")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the separation between request, contract, evidence, and finding adoption.")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    errors = validate(load_json(args.ledger))
    result = {"valid": not errors, "errors": errors}
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
