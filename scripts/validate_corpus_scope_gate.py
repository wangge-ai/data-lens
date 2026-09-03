from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


def validate(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["scope gate must be an object"]
    errors: list[str] = []
    if payload.get("contract_version") != "data-lens-corpus-scope-gate/1.0":
        errors.append("unsupported corpus scope gate contract")
    if not str(payload.get("decision_question") or "").strip():
        errors.append("decision_question is required")
    request = payload.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("succeeded"), bool):
        errors.append("request.succeeded must be boolean")
        request = {"succeeded": False}
    shared = payload.get("shared_scope")
    if not isinstance(shared, dict):
        errors.append("shared_scope must be an object")
        shared = {}
    families = payload.get("families")
    if not isinstance(families, list):
        errors.append("families must be an array")
        families = []
    family_ids = [str(item.get("family_id") or "") for item in families if isinstance(item, dict)]
    if any(not value for value in family_ids) or len(family_ids) != len(set(family_ids)):
        errors.append("family ids must be present and unique")
    ready = [item for item in families if isinstance(item, dict) and item.get("analysis_ready") is True]
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
        coverage = {}
    if coverage.get("ready_family_count") != len(ready):
        errors.append("coverage.ready_family_count does not match families")
    selection = payload.get("selection")
    if not isinstance(selection, dict):
        errors.append("selection must be an object")
        selection = {}
    scope_type = selection.get("scope_type")
    selected_sources = payload.get("selected_source_ids")
    if not isinstance(selected_sources, list):
        errors.append("selected_source_ids must be an array")
        selected_sources = []
    whole_allowed = payload.get("whole_corpus_synthesis_allowed")
    expected_whole_allowed = bool(
        request.get("succeeded") is True
        and shared.get("contract_and_evidence_valid") is True
        and shared.get("question_spans_families") is True
    )
    if whole_allowed is not expected_whole_allowed:
        errors.append("whole_corpus_synthesis_allowed is inconsistent with shared scope")
    if payload.get("next_action") == "analysis_ready":
        if payload.get("deep_analysis_allowed") is not True:
            errors.append("analysis_ready requires deep_analysis_allowed=true")
        if selection.get("valid") is not True or selection.get("authorized_by_user") is not True:
            errors.append("analysis_ready requires a valid authorized selection")
        if scope_type == "family":
            family_id = str(payload.get("selected_family_id") or "")
            selected = next((item for item in ready if item.get("family_id") == family_id), None)
            if selected is None:
                errors.append("selected family is not analysis-ready")
            elif set(map(str, selected_sources)) != set(map(str, selected.get("source_container_ids") or [])):
                errors.append("selected_source_ids do not match selected family")
        elif scope_type == "whole_corpus":
            if whole_allowed is not True:
                errors.append("whole-corpus analysis is not allowed")
        else:
            errors.append("analysis_ready requires family or whole_corpus scope")
    elif payload.get("deep_analysis_allowed") is not False:
        errors.append("non-ready scope must set deep_analysis_allowed=false")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a compiled corpus scope selection gate.")
    parser.add_argument("gate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        guard_cli_output(parser, args.output, [args.gate])
    errors = validate(load_json(args.gate))
    result = {"valid": not errors, "errors": errors}
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
