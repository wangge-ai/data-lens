from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, load_json, write_json


VERIFIED_STATUSES = {
    "verified",
    "verified_local",
    "derived_verified",
    "bounded_verified",
    "formula_verified",
    "source_stated",
    "source_stated_directional",
}
CLAIM_LEVELS = {"fact", "calculation", "pattern", "relationship", "mechanism_hypothesis"}
INFERENCE_LEVELS = {"pattern", "relationship", "mechanism_hypothesis"}
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


def _verify_locator(path: Path, locator: Any) -> list[str]:
    if not isinstance(locator, dict):
        return ["locator_missing"]
    kind = locator.get("type")
    try:
        if kind == "json_pointer":
            actual = _json_pointer(load_json(path), str(locator.get("pointer") or ""))
            if "expected" in locator and actual != locator["expected"]:
                return ["locator_expected_mismatch"]
        elif kind == "line_range":
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            start, end = int(locator["start"]), int(locator["end"])
            if start < 1 or end < start or end > len(lines):
                return ["locator_line_range_invalid"]
            quote = str(locator.get("quote") or "").strip()
            if quote and re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", "\n".join(lines[start - 1:end])):
                return ["locator_quote_mismatch"]
        elif kind == "csv_row":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
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


def adapt_deep_evidence(payload: Any, base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        rows = payload["cards"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("deep evidence cards must be a list or an object containing cards")
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
                elif file_sha256(source_path) != declared_sha256:
                    verification_errors.append("source_sha256_mismatch")
                verification_errors.extend(_verify_locator(source_path, locator))
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
            "caveat": row.get("caveat") or row.get("cannot_prove"),
            "status": status or ("verified" if verified else "unverified"),
        }
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


def compile_findings(
    candidate_payload: Any,
    evidence_payload: Any,
    scope_gate: dict[str, Any],
    evidence_base_dir: Path | None = None,
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
            contract_errors.append("claim_level is invalid; causal claims are not supported by this engine")
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

        all_refs = list(dict.fromkeys(support_refs + counter_refs + alternative_refs + robustness_refs))
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
        anchor_eligible = (
            adopted
            and coverage_valid
            and alternatives_valid
            and robustness_supportive
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
            },
            "finding": {
                "title": _text(row, "title"),
                "claim": _text(row, "claim"),
                "claim_level": claim_level,
                "analysis_unit": _text(row, "analysis_unit"),
                "decision_relevance": _text(row, "decision_relevance"),
                "baseline": _text(row, "baseline"),
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
                "decision_delta": _text(row, "decision_delta"),
                "confidence": confidence,
            },
        })

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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.candidates, args.evidence_cards, args.scope_gate])
    ledger = compile_findings(
        load_json(args.candidates), load_json(args.evidence_cards), load_json(args.scope_gate),
        args.evidence_cards.parent,
    )
    write_json(args.output, ledger)
    print(json.dumps({"output": str(args.output.resolve()), "summary": ledger["summary"], "completion_status": ledger["completion_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
