from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


VERIFIED_STATUSES = {
    "verified",
    "verified_local",
    "derived_verified",
    "bounded_verified",
    "formula_verified",
    "source_stated",
    "source_stated_directional",
}
ADOPT_VALUES = {"adopt", "adopted", "proposed_adopted"}
REJECT_VALUES = {"reject", "rejected", "proposed_rejected"}


def adapt_evidence_cards(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        rows = payload["cards"]
    elif isinstance(payload, dict) and isinstance(payload.get("evidence_index"), dict):
        rows = [dict(value, id=key) for key, value in payload["evidence_index"].items() if isinstance(value, dict)]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("evidence cards must be a list or an object containing cards/evidence_index")
    output: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"evidence card {index} must be an object")
        evidence_id = str(row.get("evidence_id") or row.get("id") or "").strip()
        if not evidence_id or evidence_id in output:
            raise ValueError(f"evidence card id is missing or duplicated: {evidence_id or index}")
        claim = str(row.get("claim") or row.get("observed_fact") or "").strip()
        source = row.get("source") if row.get("source") is not None else row.get("source_ref")
        status = str(row.get("status") or "").strip()
        explicit_verified = row.get("verified")
        verified = explicit_verified if isinstance(explicit_verified, bool) else status in VERIFIED_STATUSES
        verification_errors: list[str] = []
        if verified and not claim:
            verification_errors.append("claim_missing")
        if verified and source in (None, "", []):
            verification_errors.append("source_missing")
        if verification_errors:
            verified = False
        output[evidence_id] = {
            "verified": verified,
            "verification_errors": verification_errors,
            "claim": claim,
            "source": source,
            "locator": row.get("locator"),
            "status": status or ("verified" if verified else "unverified"),
            "family_id": row.get("family_id"),
            "lane": row.get("lane") or row.get("type"),
            "caveat": row.get("caveat") or row.get("cannot_prove"),
        }
    return output


def _required_text(row: dict[str, Any], key: str, aliases: tuple[str, ...] = ()) -> str:
    value = row.get(key)
    if value in (None, ""):
        for alias in aliases:
            if row.get(alias) not in (None, ""):
                value = row[alias]
                break
    return str(value or "").strip()


def _validate_coverage(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["coverage_plan must be an object"]
    errors = []
    if not str(value.get("strategy") or "").strip():
        errors.append("coverage_plan.strategy is required")
    for field in ("eligible_units", "reviewed_units"):
        number = value.get(field)
        if not isinstance(number, int) or number < 0:
            errors.append(f"coverage_plan.{field} must be a non-negative integer")
    if isinstance(value.get("eligible_units"), int) and isinstance(value.get("reviewed_units"), int):
        if value["reviewed_units"] > value["eligible_units"]:
            errors.append("coverage_plan.reviewed_units exceeds eligible_units")
    if not isinstance(value.get("families_covered"), list):
        errors.append("coverage_plan.families_covered must be an array")
    if not isinstance(value.get("limitations"), list):
        errors.append("coverage_plan.limitations must be an array")
    return errors


def _adapt_candidate(row: dict[str, Any], index: int) -> dict[str, Any]:
    candidate_id = _required_text(row, "candidate_id", ("angle_id", "id"))
    proposed = _required_text(row, "proposed_status", ("status",)).lower()
    evidence_refs = row.get("evidence_refs") or []
    required_evidence = row.get("required_evidence") or []
    return {
        "candidate_id": candidate_id,
        "title": _required_text(row, "title"),
        "question": _required_text(row, "question"),
        "why_worthwhile": _required_text(row, "why_worthwhile", ("reason",)),
        "analysis_unit": _required_text(row, "analysis_unit"),
        "required_evidence": required_evidence,
        "coverage_plan": row.get("coverage_plan"),
        "counterexample_check": _required_text(row, "counterexample_check", ("possible_counterexample",)),
        "failure_condition": _required_text(row, "failure_condition"),
        "evidence_refs": evidence_refs,
        "proposed_status": proposed,
        "rejection_reason": _required_text(row, "rejection_reason"),
        "decision_value": row.get("decision_value"),
        "source_index": index,
    }


def compile_angles(candidate_payload: Any, evidence_payload: Any) -> dict[str, Any]:
    if not isinstance(candidate_payload, dict):
        raise ValueError("candidate payload must be an object so the original decision question and request state are preserved")
    decision_question = str(candidate_payload.get("decision_question") or "").strip()
    if not decision_question:
        raise ValueError("decision_question is required and must preserve the user's original question")
    rows = candidate_payload.get("candidates") if isinstance(candidate_payload, dict) else candidate_payload
    if isinstance(candidate_payload, dict) and rows is None:
        rows = candidate_payload.get("angles")
    if not isinstance(rows, list):
        raise ValueError("candidate payload must be a list or an object containing candidates/angles")
    if len(rows) > 8:
        raise ValueError("angle discovery accepts at most 8 candidates")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("every angle candidate must be an object")
    adapted = [_adapt_candidate(row, index) for index, row in enumerate(rows)]
    proposed_adoptions = sum(1 for row in adapted if row["proposed_status"] in ADOPT_VALUES)
    if proposed_adoptions > 4:
        raise ValueError("angle discovery accepts at most 4 proposed adoptions")
    evidence_index = adapt_evidence_cards(evidence_payload)
    request = candidate_payload.get("request", {}) if isinstance(candidate_payload, dict) else {}
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if not isinstance(request.get("attempted"), bool) or not isinstance(request.get("succeeded"), bool):
        raise ValueError("request.attempted and request.succeeded must be boolean")
    request_count = request.get("request_count")
    if not isinstance(request_count, int) or isinstance(request_count, bool) or request_count < 0:
        raise ValueError("request.request_count must be a non-negative integer")
    if request["succeeded"] and (not request["attempted"] or request_count < 1):
        raise ValueError("a successful request requires attempted=true and request_count>=1")
    if not request["attempted"] and request_count != 0:
        raise ValueError("an unattempted request requires request_count=0")
    request_record = {
        "attempted": bool(request.get("attempted", False)),
        "succeeded": bool(request.get("succeeded", False)),
        "provider": request.get("provider"),
        "request_count": request_count,
    }
    seen: set[str] = set()
    compiled: list[dict[str, Any]] = []
    for row in adapted:
        contract_errors: list[str] = []
        candidate_id = row["candidate_id"]
        if not candidate_id:
            contract_errors.append("candidate_id is required")
        elif candidate_id in seen:
            contract_errors.append("candidate_id is duplicated")
        seen.add(candidate_id)
        for field in ("title", "question", "why_worthwhile", "analysis_unit", "counterexample_check", "failure_condition"):
            if not row[field]:
                contract_errors.append(f"{field} is required")
        if (
            not isinstance(row["required_evidence"], list)
            or not row["required_evidence"]
            or any(not str(value).strip() for value in row["required_evidence"])
        ):
            contract_errors.append("required_evidence must be a non-empty array")
        contract_errors.extend(_validate_coverage(row["coverage_plan"]))
        if not isinstance(row["evidence_refs"], list):
            contract_errors.append("evidence_refs must be an array")
            row["evidence_refs"] = []
        elif any(not isinstance(ref, str) or not ref.strip() for ref in row["evidence_refs"]):
            contract_errors.append("evidence_refs must contain non-empty strings")
        if row["proposed_status"] not in ADOPT_VALUES | REJECT_VALUES:
            contract_errors.append("proposed_status must be adopted or rejected")
        if row["proposed_status"] in REJECT_VALUES and not row["rejection_reason"]:
            contract_errors.append("rejected angle requires rejection_reason")
        if row["proposed_status"] in ADOPT_VALUES and isinstance(row["coverage_plan"], dict):
            if row["coverage_plan"].get("eligible_units", 0) < 1 or row["coverage_plan"].get("reviewed_units", 0) < 1:
                contract_errors.append("adopted angle requires at least one eligible and reviewed unit")
        evidence_errors: list[str] = []
        for ref in row["evidence_refs"]:
            if ref not in evidence_index:
                evidence_errors.append(f"unknown evidence reference: {ref}")
            elif evidence_index[ref]["verified"] is not True:
                evidence_errors.append(f"unverified evidence reference: {ref}")
        if row["proposed_status"] in ADOPT_VALUES and not row["evidence_refs"]:
            evidence_errors.append("adopted angle requires verified evidence")
        contract_valid = not contract_errors
        evidence_valid = not evidence_errors and bool(row["evidence_refs"])
        adopted = (
            row["proposed_status"] in ADOPT_VALUES
            and request_record["succeeded"]
            and contract_valid
            and evidence_valid
        )
        rejection_reason = row["rejection_reason"] or None
        if not adopted and row["proposed_status"] in ADOPT_VALUES:
            reasons = []
            if not request_record["succeeded"]:
                reasons.append("request_not_succeeded")
            if contract_errors:
                reasons.append("contract_invalid")
            if evidence_errors:
                reasons.append("evidence_invalid")
            rejection_reason = ";".join(reasons) or "not_adopted"
        compiled.append(
            {
                "candidate_id": candidate_id or f"invalid-{row['source_index'] + 1}",
                "contract_valid": contract_valid,
                "contract_errors": contract_errors,
                "evidence_valid": evidence_valid,
                "evidence_errors": evidence_errors,
                "evidence_refs": row["evidence_refs"],
                "adopted": adopted,
                "rejection_reason": rejection_reason,
                "angle": {
                    key: row[key]
                    for key in (
                        "title", "question", "why_worthwhile", "analysis_unit", "required_evidence",
                        "coverage_plan", "counterexample_check", "failure_condition", "decision_value",
                    )
                },
            }
        )
    adopted_count = sum(1 for row in compiled if row["adopted"])
    return {
        "contract_version": "data-lens-adoption-ledger/1.0",
        "request": request_record,
        "evidence_index": evidence_index,
        "candidates": compiled,
        "summary": {
            "candidate_count": len(compiled),
            "adopted_count": adopted_count,
            "core_question_answered": adopted_count > 0,
            "decision_question": decision_question,
        },
        "completion_status": "partial" if adopted_count else "core_question_unanswered",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Adapt, strictly validate, evidence-check, and adopt automatic analysis angles.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ledger = compile_angles(load_json(args.candidates), load_json(args.evidence_cards))
    write_json(args.output, ledger)
    print(json.dumps({"output": str(args.output.resolve()), "summary": ledger["summary"], "completion_status": ledger["completion_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
