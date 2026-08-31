from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from prepare_table_reviews import VALID_ANALYSIS_ROLES, sheet_id
from validate_mixed_workspace import read_jsonl, validate_workspace, version_at_least


FINAL_FAMILY_STATES = {"full_census_complete", "stable_two_batches"}
FINAL_FAMILY_REVIEW = {"reviewed", "completed"}


def validate_gates(workspace: Path, report_mode: str, depth: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required = {
        "inventory": workspace / "inventory.json",
        "sample": workspace / "sample_selection.json",
        "run_state": workspace / "run_state.json",
        "tables": workspace / "tables_screening.json",
        "table_reviews": workspace / "table_reviews.jsonl",
    }
    for name, path in required.items():
        if not path.is_file():
            errors.append(f"gate_artifact_missing:{name}:{path.name}")
    if errors:
        return {"valid": False, "report_mode": report_mode, "report_eligible": False, "errors": errors, "warnings": warnings, "checks": {}}

    workspace_validation = validate_workspace(workspace, allow_incomplete=False)
    if not workspace_validation["valid"]:
        errors.extend(f"mixed_workspace:{item}" for item in workspace_validation["errors"])
    warnings.extend(f"mixed_workspace:{item}" for item in workspace_validation["warnings"])

    inventory = load_json(required["inventory"])
    sample = load_json(required["sample"])
    state = load_json(required["run_state"])
    tables = load_json(required["tables"])
    reviews = read_jsonl(required["table_reviews"])

    directory_coverage = sample.get("directory_coverage") or []
    if not directory_coverage:
        errors.append("directory_coverage_missing")
    missed_directories = [str(item.get("directory")) for item in directory_coverage if int(item.get("eligible_count") or 0) > 0 and int(item.get("selected_count") or 0) == 0]
    if missed_directories:
        errors.append("selected_directories_missing:" + "|".join(sorted(missed_directories)))

    selected_paths = {
        str(Path(str(item.get("path") or "")).resolve()).lower(): str(item.get("source_container_id") or "")
        for item in sample.get("selected", []) if item.get("path") and item.get("evidence_role") in {"tabular_data", "performance_table", "audience_voice"}
    }
    expected_sheets: dict[str, tuple[str, str]] = {}
    parsed_selected_paths: set[str] = set()
    for workbook in tables.get("files", []):
        normalized = str(Path(str(workbook.get("path") or "")).resolve()).lower()
        if normalized not in selected_paths:
            continue
        parsed_selected_paths.add(normalized)
        for sheet in workbook.get("sheets", []):
            if int(sheet.get("nonempty_cells") or 0) > 0:
                sid = sheet_id(str(workbook.get("path")), str(sheet.get("name")))
                expected_sheets[sid] = (str(workbook.get("path")), str(sheet.get("name")))
    for missing_path in sorted(set(selected_paths) - parsed_selected_paths):
        errors.append(f"selected_table_source_not_parsed:{selected_paths[missing_path]}:{Path(missing_path).name}")
    reviews_by_id = {str(item.get("sheet_id")): item for item in reviews}
    for sid, (path, name) in expected_sheets.items():
        review = reviews_by_id.get(sid)
        if review is None:
            errors.append(f"table_sheet_review_missing:{sid}:{Path(path).name}:{name}")
            continue
        status = review.get("review_status")
        role = review.get("analysis_role")
        if status not in {"reviewed", "excluded"}:
            errors.append(f"table_sheet_review_pending:{sid}")
        if role not in VALID_ANALYSIS_ROLES or role == "unassigned":
            errors.append(f"table_sheet_role_unassigned:{sid}")
        if not review.get("decision_reason"):
            errors.append(f"table_sheet_reason_missing:{sid}")
        if status == "excluded" and review.get("can_support_claims"):
            errors.append(f"excluded_sheet_claim_eligible:{sid}")
        if role in {"coding_template", "audience_voice_synthetic", "excluded_unrelated"} and review.get("can_support_claims"):
            errors.append(f"ineligible_sheet_claim_eligible:{sid}:{role}")
    extra_reviews = sorted(set(reviews_by_id) - set(expected_sheets))
    if extra_reviews:
        warnings.append(f"table_reviews_outside_selected_sample:{len(extra_reviews)}")

    selected_families = [item for item in state.get("families", []) if int(item.get("selected_count") or 0) > 0]
    if version_at_least(str(state.get("skill_version") or ""), (0, 7)):
        for family in selected_families:
            label = str(family.get("label") or "<missing>")
            if family.get("expansion_status") == "full_census_complete" and not family.get("eligible_count_known", True):
                errors.append(f"family_full_census_with_unknown_eligibility:{label}")
            if family.get("expansion_status") == "stable_two_batches":
                basis = family.get("stability_basis") or {}
                required_lanes = set(basis.get("required_lanes") or [])
                covered_lanes = set(basis.get("covered_lanes") or [])
                if basis.get("mode") != "comparable_batches" or not required_lanes.issubset(covered_lanes):
                    errors.append(f"family_stability_basis_invalid:{label}")
                if not basis.get("stable_comparison_key") or len(basis.get("no_new_batch_ids") or []) != 2:
                    errors.append(f"family_comparable_batches_missing:{label}")
    unstable = [str(item.get("label")) for item in selected_families if item.get("expansion_status") not in FINAL_FAMILY_STATES or item.get("status") not in FINAL_FAMILY_REVIEW]
    if unstable:
        message = "family_stability_incomplete:" + "|".join(sorted(unstable))
        if report_mode == "final" and depth == "deep":
            errors.append(message)
        else:
            warnings.append(message)

    placeholder_labels = {"其他", "待识别资料", "待筛查表格"}
    placeholder_selected = sum(int(item.get("selected_count") or 0) for item in selected_families if item.get("label") in placeholder_labels)
    total_selected = sum(int(item.get("selected_count") or 0) for item in selected_families)
    if placeholder_selected:
        warnings.append(f"placeholder_family_selected:{placeholder_selected}/{total_selected}")

    stages = state.get("stages") or {}
    for stage in ("semantic_review", "family_synthesis", "cross_family_synthesis"):
        if stages.get(stage) != "completed":
            errors.append(f"required_stage_incomplete:{stage}:{stages.get(stage)}")
    if stages.get("table_review") not in {None, "completed"}:
        errors.append(f"required_stage_incomplete:table_review:{stages.get('table_review')}")

    valid = not errors
    return {
        "gate_version": "1.0",
        "valid": valid,
        "report_mode": report_mode,
        "report_depth": depth,
        "report_eligible": valid,
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "canonical_items": int((inventory.get("summary") or {}).get("canonical_items") or 0),
            "selected_directories": len(directory_coverage) - len(missed_directories),
            "eligible_directories": len(directory_coverage),
            "selected_table_sheets": len(expected_sheets),
            "reviewed_table_sheets": sum(1 for sid in expected_sheets if (reviews_by_id.get(sid) or {}).get("review_status") in {"reviewed", "excluded"}),
            "selected_families": len(selected_families),
            "unstable_families": len(unstable),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply final/preliminary report gates to a Data Lens mixed workspace.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--report-mode", choices=["final", "preliminary"], required=True)
    parser.add_argument("--depth", choices=["brief", "standard", "deep"], required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    args = parser.parse_args()
    result = validate_gates(args.workspace, args.report_mode, args.depth)
    write_json(args.json_report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
