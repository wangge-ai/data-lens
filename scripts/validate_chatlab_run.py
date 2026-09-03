from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, load_json, write_json
from validate_adoption_ledger import validate as validate_angle_ledger
from validate_corpus_scope_gate import validate as validate_scope_gate
from validate_finding_ledger import validate as validate_finding_ledger


def _input(role: str, path: Path) -> dict[str, Any]:
    return {"role": role, "path": str(path.resolve()), "sha256": file_sha256(path)}


def validate_chatlab_run(
    profile_path: Path,
    scope_path: Path,
    angle_path: Path,
    finding_path: Path,
    plan_path: Path,
    report_mode: str,
    report_depth: str,
) -> dict[str, Any]:
    paths = {
        "chatlab_profile": profile_path,
        "corpus_scope_gate": scope_path,
        "angle_adoption_ledger": angle_path,
        "finding_adoption_ledger": finding_path,
        "analysis_plan": plan_path,
    }
    errors: list[str] = []
    warnings: list[str] = []
    for role, path in paths.items():
        if not path.is_file():
            errors.append(f"input_missing:{role}:{path}")
    if errors:
        return {
            "gate_version": "data-lens-chatlab-run-gate/1.0",
            "valid": False,
            "report_mode": report_mode,
            "report_depth": report_depth,
            "route": "qualitative_corpus",
            "report_eligible": False,
            "errors": errors,
            "warnings": warnings,
            "inputs": [],
            "checks": {},
        }

    profile = load_json(profile_path)
    scope = load_json(scope_path)
    angles = load_json(angle_path)
    findings = load_json(finding_path)
    plan = load_json(plan_path)
    if profile.get("contract_version") != "data-lens-chatlab-corpus-profile/0.1":
        errors.append("unsupported_chatlab_profile")
    errors.extend(f"scope:{item}" for item in validate_scope_gate(scope))
    errors.extend(f"angles:{item}" for item in validate_angle_ledger(angles))
    errors.extend(f"findings:{item}" for item in validate_finding_ledger(findings))

    decision_question = str(scope.get("decision_question") or "").strip()
    if not decision_question:
        errors.append("decision_question_missing")
    if str(plan.get("decision_question") or "").strip() != decision_question:
        errors.append("plan_decision_question_mismatch")
    if str((angles.get("summary") or {}).get("decision_question") or "").strip() != decision_question:
        errors.append("angle_decision_question_mismatch")
    if str(findings.get("decision_question") or "").strip() != decision_question:
        errors.append("finding_decision_question_mismatch")
    if plan.get("primary_route") != "qualitative_corpus":
        errors.append(f"route_invalid:{plan.get('primary_route')}")
    if scope.get("next_action") != "analysis_ready" or scope.get("deep_analysis_allowed") is not True:
        errors.append("scope_not_analysis_ready")

    profile_source_ids = {
        str(item.get("source_container_id") or "")
        for item in profile.get("conversations", [])
        if str(item.get("source_container_id") or "")
    }
    selected_source_ids = {str(value) for value in scope.get("selected_source_ids", []) if str(value)}
    if not selected_source_ids:
        errors.append("selected_sources_empty")
    elif selected_source_ids != profile_source_ids:
        errors.append("profile_scope_source_mismatch")

    source_hash_failures = 0
    for conversation in profile.get("conversations", []):
        source = Path(str(conversation.get("source_path") or ""))
        declared_hash = str(conversation.get("source_sha256") or "").lower()
        if not source.is_file() or not declared_hash or file_sha256(source) != declared_hash:
            source_hash_failures += 1
    if source_hash_failures:
        errors.append(f"conversation_source_hash_failures:{source_hash_failures}")

    angle_summary = angles.get("summary") or {}
    finding_summary = findings.get("summary") or {}
    if int(angle_summary.get("adopted_count") or 0) < 1:
        errors.append("no_adopted_angle")
    if report_mode == "final" and (
        finding_summary.get("core_question_answered") is not True
        or int(finding_summary.get("anchor_finding_count") or 0) < 1
    ):
        errors.append("final_requires_anchor_finding")
    if int((profile.get("summary") or {}).get("failed_json_files") or 0):
        warnings.append("profile_contains_json_parse_failures")
    if profile.get("failure_ledger"):
        warnings.append(f"profile_failure_ledger_entries:{len(profile['failure_ledger'])}")

    valid = not errors
    return {
        "gate_version": "data-lens-chatlab-run-gate/1.0",
        "valid": valid,
        "report_mode": report_mode,
        "report_depth": report_depth,
        "route": "qualitative_corpus",
        "report_eligible": valid,
        "errors": errors,
        "warnings": warnings,
        "inputs": [_input(role, path) for role, path in paths.items()],
        "checks": {
            "canonical_conversations": int((profile.get("summary") or {}).get("canonical_conversations") or 0),
            "messages": int((profile.get("summary") or {}).get("messages_in_canonical_exports") or 0),
            "semantic_candidates": int(sum(int(item.get("semantic_candidate_count") or 0) for item in profile.get("conversations", []))),
            "review_samples": int((profile.get("summary") or {}).get("review_sample_count") or 0),
            "selected_sources": len(selected_source_ids),
            "adopted_angles": int(angle_summary.get("adopted_count") or 0),
            "adopted_findings": int(finding_summary.get("adopted_count") or 0),
            "anchor_findings": int(finding_summary.get("anchor_finding_count") or 0),
            "source_hash_failures": source_hash_failures,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a ChatLab qualitative run before report rendering.")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--scope-gate", type=Path, required=True)
    parser.add_argument("--angle-ledger", type=Path, required=True)
    parser.add_argument("--finding-ledger", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report-mode", choices=("final", "preliminary"), default="final")
    parser.add_argument("--depth", choices=("brief", "standard", "deep"), default="deep")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(
        parser,
        args.output,
        [args.profile, args.scope_gate, args.angle_ledger, args.finding_ledger, args.plan],
    )
    result = validate_chatlab_run(
        args.profile,
        args.scope_gate,
        args.angle_ledger,
        args.finding_ledger,
        args.plan,
        args.report_mode,
        args.depth,
    )
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
