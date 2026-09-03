from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


VERIFIED_STATUSES = {
    "verified",
    "verified_local",
    "derived_verified",
    "bounded_verified",
    "formula_verified",
    "source_stated",
    "source_stated_directional",
}
VALID_READINESS = {"ready", "needs_review", "not_analyzable"}
VALID_SCOPE_TYPES = {"none", "family", "whole_corpus"}
VALID_SELECTION_BASES = {"none", "user_selected", "explicit_shared_scope", "automatic_unique_ready"}
VALID_ROUTES = {
    "tabular_analysis",
    "repeated_operational_tables",
    "qualitative_corpus",
    "same_author_content",
    "account_content_performance",
    "method_corpus",
    "multimodal_evidence",
    "mixed_corpus",
    "novel_route",
}


def _request(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    value = payload.get("request")
    errors: list[str] = []
    if not isinstance(value, dict):
        return {"attempted": False, "succeeded": False, "provider": None, "request_count": 0}, ["request must be an object"]
    attempted = value.get("attempted")
    succeeded = value.get("succeeded")
    request_count = value.get("request_count")
    if not isinstance(attempted, bool) or not isinstance(succeeded, bool):
        errors.append("request.attempted and request.succeeded must be boolean")
    if not isinstance(request_count, int) or isinstance(request_count, bool) or request_count < 0:
        errors.append("request.request_count must be a non-negative integer")
        request_count = 0
    if succeeded is True and (attempted is not True or request_count < 1):
        errors.append("a successful classification request requires attempted=true and request_count>=1")
    if attempted is False and request_count != 0:
        errors.append("an unattempted classification request requires request_count=0")
    return {
        "attempted": attempted if isinstance(attempted, bool) else False,
        "succeeded": succeeded if isinstance(succeeded, bool) else False,
        "provider": value.get("provider"),
        "request_count": request_count,
    }, errors


def _evidence_index(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        rows = payload["cards"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("evidence cards must be a list or an object containing cards")
    output: dict[str, dict[str, Any]] = {}
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
        locator = row.get("locator")
        verification_errors: list[str] = []
        if verified and not claim:
            verification_errors.append("claim_missing")
        if verified and source in (None, "", []):
            verification_errors.append("source_missing")
        if verified and not isinstance(locator, dict):
            verification_errors.append("locator_missing")
        if verification_errors:
            verified = False
        output[evidence_id] = {
            "verified": verified,
            "verification_errors": verification_errors,
            "claim": claim,
            "source": source,
            "locator": locator,
            "family_id": row.get("family_id"),
            "lane": row.get("lane") or row.get("type"),
            "status": status or ("verified" if verified else "unverified"),
        }
    return output


def _canonical_sources(inventory: dict[str, Any]) -> set[str]:
    source_ids = {
        str(item.get("source_container_id") or "").strip()
        for item in inventory.get("files", [])
        if item.get("canonical", True)
    }
    source_ids.discard("")
    return source_ids


def _verified_refs(refs: Any, evidence: dict[str, dict[str, Any]], prefix: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if not isinstance(refs, list):
        return [], [f"{prefix}.evidence_refs must be an array"]
    normalized = [str(ref).strip() for ref in refs if str(ref).strip()]
    if len(normalized) != len(refs):
        errors.append(f"{prefix}.evidence_refs must contain non-empty strings")
    for ref in normalized:
        if ref not in evidence:
            errors.append(f"{prefix}.unknown_evidence:{ref}")
        elif evidence[ref]["verified"] is not True:
            errors.append(f"{prefix}.unverified_evidence:{ref}")
    return normalized, errors


def compile_scope(candidate_payload: Any, evidence_payload: Any, inventory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate_payload, dict):
        raise ValueError("scope candidates must be an object")
    decision_question = str(candidate_payload.get("decision_question") or "").strip()
    if not decision_question:
        raise ValueError("decision_question is required and must preserve the user's original request")
    request, request_errors = _request(candidate_payload)
    evidence = _evidence_index(evidence_payload)
    inventory_sources = _canonical_sources(inventory)
    if not inventory_sources:
        raise ValueError("inventory must contain canonical source_container_id values")

    shared = candidate_payload.get("shared_scope")
    shared_errors: list[str] = []
    if not isinstance(shared, dict):
        shared = {}
        shared_errors.append("shared_scope must be an object")
    object_status = str(shared.get("shared_object_status") or "candidate")
    problem_status = str(shared.get("shared_problem_status") or "candidate")
    if object_status not in {"confirmed", "candidate", "absent"}:
        shared_errors.append("shared_scope.shared_object_status is invalid")
    if problem_status not in {"confirmed", "candidate", "absent"}:
        shared_errors.append("shared_scope.shared_problem_status is invalid")
    shared_refs, ref_errors = _verified_refs(shared.get("evidence_refs") or [], evidence, "shared_scope")
    shared_errors.extend(ref_errors)
    question_spans_families = shared.get("question_spans_families")
    if not isinstance(question_spans_families, bool):
        shared_errors.append("shared_scope.question_spans_families must be boolean")
        question_spans_families = False
    shared_confirmed = (
        object_status == "confirmed"
        and problem_status == "confirmed"
        and bool(str(shared.get("shared_object") or "").strip())
        and bool(str(shared.get("shared_problem") or "").strip())
        and bool(shared_refs)
        and not shared_errors
    )

    rows = candidate_payload.get("families")
    if not isinstance(rows, list):
        raise ValueError("families must be an array")
    seen_families: set[str] = set()
    assigned_sources: dict[str, str] = {}
    compiled_families: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"family {index} must be an object")
        prefix = f"families[{index}]"
        family_id = str(row.get("family_id") or "").strip()
        errors: list[str] = []
        if not family_id:
            errors.append(f"{prefix}.family_id is required")
            family_id = f"invalid-{index + 1}"
        elif family_id in seen_families:
            errors.append(f"{prefix}.family_id is duplicated")
        seen_families.add(family_id)
        label = str(row.get("label") or "").strip()
        shared_object = str(row.get("shared_object") or "").strip()
        analysis_unit = str(row.get("analysis_unit") or "").strip()
        readiness = str(row.get("readiness") or "needs_review")
        route = str(row.get("recommended_route") or "novel_route")
        if not label:
            errors.append(f"{prefix}.label is required")
        if not shared_object:
            errors.append(f"{prefix}.shared_object is required")
        if not analysis_unit:
            errors.append(f"{prefix}.analysis_unit is required")
        if readiness not in VALID_READINESS:
            errors.append(f"{prefix}.readiness is invalid")
        if route not in VALID_ROUTES:
            errors.append(f"{prefix}.recommended_route is invalid")
        source_ids = row.get("source_container_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{prefix}.source_container_ids must be a non-empty array")
            source_ids = []
        normalized_sources: list[str] = []
        for source_id in source_ids:
            value = str(source_id).strip()
            if not value:
                errors.append(f"{prefix}.source_container_ids contains an empty value")
                continue
            if value not in inventory_sources:
                errors.append(f"{prefix}.unknown_source:{value}")
            if value in assigned_sources and assigned_sources[value] != family_id:
                errors.append(f"{prefix}.source_assigned_to_multiple_families:{value}")
            else:
                assigned_sources[value] = family_id
            normalized_sources.append(value)
        questions = row.get("candidate_questions")
        if not isinstance(questions, list) or not questions or any(not str(value).strip() for value in questions):
            errors.append(f"{prefix}.candidate_questions must contain at least one non-empty question")
            questions = []
        refs, evidence_errors = _verified_refs(row.get("evidence_refs") or [], evidence, prefix)
        for ref in refs:
            card = evidence.get(ref)
            if card and card.get("verified") is True and str(card.get("family_id") or "") != family_id:
                evidence_errors.append(f"{prefix}.evidence_family_mismatch:{ref}")
        if readiness == "ready" and not refs:
            evidence_errors.append(f"{prefix}.ready_family_requires_verified_evidence")
        contract_valid = not errors
        evidence_valid = not evidence_errors and bool(refs)
        compiled_families.append({
            "family_id": family_id,
            "label": label,
            "shared_object": shared_object,
            "analysis_unit": analysis_unit,
            "recommended_route": route,
            "source_container_ids": normalized_sources,
            "candidate_questions": [str(value).strip() for value in questions],
            "declared_readiness": readiness,
            "contract_valid": contract_valid,
            "contract_errors": errors,
            "evidence_valid": evidence_valid,
            "evidence_errors": evidence_errors,
            "evidence_refs": refs,
            "analysis_ready": request["succeeded"] and readiness == "ready" and contract_valid and evidence_valid,
        })

    selection = candidate_payload.get("selection")
    selection_errors: list[str] = []
    if not isinstance(selection, dict):
        selection = {}
        selection_errors.append("selection must be an object")
    scope_type = str(selection.get("scope_type") or "none")
    scope_id = str(selection.get("scope_id") or "").strip() or None
    basis = str(selection.get("basis") or "none")
    authorized = selection.get("authorized_by_user")
    if scope_type not in VALID_SCOPE_TYPES:
        selection_errors.append("selection.scope_type is invalid")
    if basis not in VALID_SELECTION_BASES:
        selection_errors.append("selection.basis is invalid")
    if not isinstance(authorized, bool):
        selection_errors.append("selection.authorized_by_user must be boolean")
        authorized = False
    family_index = {item["family_id"]: item for item in compiled_families}
    selected_sources: list[str] = []
    selected_family_id: str | None = None
    whole_corpus_allowed = request["succeeded"] and shared_confirmed and question_spans_families
    selection_valid = not selection_errors
    if scope_type == "family":
        selected = family_index.get(str(scope_id or ""))
        if selected is None:
            selection_errors.append("selection references an unknown family")
        elif not selected["analysis_ready"]:
            selection_errors.append("selected family is not analysis-ready")
        elif not authorized:
            selection_errors.append("family selection requires current user authorization")
        else:
            selected_family_id = selected["family_id"]
            selected_sources = list(selected["source_container_ids"])
    elif scope_type == "whole_corpus":
        if not whole_corpus_allowed:
            selection_errors.append("whole-corpus synthesis requires a verified shared object and shared problem spanning families")
        if not authorized:
            selection_errors.append("whole-corpus selection requires current user authorization")
        if scope_id not in (None, "whole_corpus"):
            selection_errors.append("whole-corpus scope_id must be whole_corpus or null")
        selected_sources = sorted(inventory_sources)
    elif scope_id is not None:
        selection_errors.append("selection.scope_id must be empty when scope_type is none")
    selection_valid = selection_valid and not selection_errors

    ready_families = [item for item in compiled_families if item["analysis_ready"]]
    if scope_type in {"family", "whole_corpus"} and selection_valid:
        next_action = "analysis_ready"
    elif request_errors or shared_errors or any(item["contract_errors"] for item in compiled_families):
        next_action = "review_required"
    elif ready_families:
        next_action = "selection_required"
    else:
        next_action = "inventory_only"

    return {
        "contract_version": "data-lens-corpus-scope-gate/1.0",
        "decision_question": decision_question,
        "request": request,
        "request_errors": request_errors,
        "evidence_index": evidence,
        "shared_scope": {
            "shared_object_status": object_status,
            "shared_object": str(shared.get("shared_object") or "").strip(),
            "shared_problem_status": problem_status,
            "shared_problem": str(shared.get("shared_problem") or "").strip(),
            "question_spans_families": question_spans_families,
            "evidence_refs": shared_refs,
            "contract_and_evidence_valid": shared_confirmed,
            "errors": shared_errors,
        },
        "families": compiled_families,
        "coverage": {
            "canonical_source_count": len(inventory_sources),
            "assigned_source_count": len(assigned_sources),
            "unassigned_source_ids": sorted(inventory_sources - set(assigned_sources)),
            "ready_family_count": len(ready_families),
        },
        "selection": {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "basis": basis,
            "authorized_by_user": authorized,
            "valid": selection_valid,
            "errors": selection_errors,
        },
        "selected_family_id": selected_family_id,
        "selected_source_ids": selected_sources,
        "whole_corpus_synthesis_allowed": whole_corpus_allowed,
        "deep_analysis_allowed": next_action == "analysis_ready",
        "next_action": next_action,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile family classification candidates into a deterministic corpus-selection gate.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.candidates, args.evidence_cards, args.inventory])
    result = compile_scope(load_json(args.candidates), load_json(args.evidence_cards), load_json(args.inventory))
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "next_action": result["next_action"],
        "ready_families": result["coverage"]["ready_family_count"],
        "selected_family_id": result["selected_family_id"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
