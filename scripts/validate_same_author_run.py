from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json, write_json


FINAL_DIMENSION_STATES = {"reviewed", "evidence_missing", "not_applicable"}
FINAL_VISUAL_STATES = {"complete", "evidence_missing", "not_required"}
NON_CONTENT_DIMENSIONS = {"visual_layout", "exceptions"}


def artifact_record(role: str, path: Path) -> dict[str, Any]:
    return {"role": role, "path": str(path.resolve()), "sha256": file_sha256(path), "size_bytes": path.stat().st_size}


def resolve_artifact(workspace: Path, supplied: Path | None, default_name: str) -> Path:
    return (supplied or (workspace / default_name)).resolve()


def validate_same_author_run(
    workspace: Path,
    report_mode: str,
    depth: str,
    *,
    extract_manifest: Path | None = None,
    review_manifest: Path | None = None,
    visual_inventory: Path | None = None,
    visual_mapping: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    paths = {
        "inventory": workspace / "inventory.json",
        "plan": workspace / "analysis_plan.json",
        "sample": workspace / "sample_selection.json",
        "extracts": resolve_artifact(workspace, extract_manifest, "content_extract_manifest.json"),
        "review": resolve_artifact(workspace, review_manifest, "same_author_review.json"),
        "visual_inventory": resolve_artifact(workspace, visual_inventory, "visual_inventory_reviewed.json"),
        "visual_mapping": resolve_artifact(workspace, visual_mapping, "wechat_visual_mapping.json"),
    }
    for role in ("inventory", "plan", "sample", "extracts"):
        if not paths[role].is_file():
            errors.append(f"gate_artifact_missing:{role}:{paths[role].name}")
    if report_mode == "final" and not paths["review"].is_file():
        errors.append(f"gate_artifact_missing:review:{paths['review'].name}")
    if errors:
        return {
            "gate_version": "same-author/2.0",
            "route": "same_author_content",
            "valid": False,
            "report_mode": report_mode,
            "report_depth": depth,
            "report_eligible": False,
            "scope_complete": False,
            "inputs": [],
            "capabilities": {},
            "errors": errors,
            "warnings": warnings,
            "checks": {},
        }

    inventory = load_json(paths["inventory"])
    plan = load_json(paths["plan"])
    sample = load_json(paths["sample"])
    extracts = load_json(paths["extracts"])
    review = load_json(paths["review"]) if paths["review"].is_file() else {}
    inputs = [artifact_record(role, paths[role]) for role in ("inventory", "plan", "sample", "extracts")]
    method_path = Path(__file__).resolve().parent.parent / "references" / "methods" / "same-author-content.md"
    inputs.append(artifact_record("method", method_path))
    for role in ("review", "visual_inventory", "visual_mapping"):
        if paths[role].is_file():
            inputs.append(artifact_record(role, paths[role]))

    if plan.get("primary_route") != "same_author_content":
        errors.append(f"route_mismatch:{plan.get('primary_route')}")
    if plan.get("comparison_unit") != "article":
        errors.append(f"comparison_unit_mismatch:{plan.get('comparison_unit')}")
    if plan.get("report_depth") and plan.get("report_depth") != depth:
        errors.append(f"plan_depth_mismatch:{plan.get('report_depth')}!={depth}")

    inventory_rows = [item for item in inventory.get("files", []) if item.get("source_container_id")]
    inventory_by_id = {str(item["source_container_id"]): item for item in inventory_rows}
    if len(inventory_by_id) != len(inventory_rows):
        errors.append("inventory_source_ids_duplicate")
    selected = sample.get("selected") or []
    selected_ids = [str(item.get("source_container_id") or "") for item in selected]
    selected_count = int(sample.get("selected_count") or 0)
    eligible_count = int(sample.get("eligible_count") or 0)
    if selected_count != len(selected):
        errors.append(f"selected_count_mismatch:{selected_count}!={len(selected)}")
    if not selected_ids or any(not value for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        errors.append("selected_source_ids_invalid")
    if sample.get("strategy") == "full_census" and selected_count != eligible_count:
        errors.append(f"full_census_incomplete:{selected_count}/{eligible_count}")
    elif selected_count < eligible_count and not sample.get("inclusion_rule"):
        errors.append("partial_sample_inclusion_rule_missing")
    if selected_count < eligible_count and not sample.get("bias_warnings"):
        errors.append("partial_sample_bias_warning_missing")
    if selected_count < 5:
        warnings.append(f"same_author_sample_below_preferred_five:{selected_count}")
    if sample.get("analysis_unit") not in {"article", "article_candidate"}:
        errors.append(f"sample_analysis_unit_invalid:{sample.get('analysis_unit')}")
    if sample.get("analysis_unit_status") != "confirmed":
        warnings.append(f"sample_analysis_unit_not_confirmed:{sample.get('analysis_unit_status')}")

    selected_groups: list[str] = []
    for source_id in selected_ids:
        row = inventory_by_id.get(source_id)
        if row is None:
            errors.append(f"selected_source_missing_from_inventory:{source_id}")
            continue
        if not row.get("canonical", True):
            errors.append(f"selected_source_not_canonical:{source_id}")
        if row.get("evidence_role") != "content_text" or row.get("container_type") != "article_candidate":
            errors.append(f"selected_source_not_article:{source_id}")
        group = str(row.get("source_family_key") or row.get("group_key") or source_id)
        selected_groups.append(group)
    if len(selected_groups) != len(set(selected_groups)):
        errors.append("multiple_variants_selected_from_same_article_family")

    extract_rows = extracts.get("records") or []
    extract_ids = [str(item.get("source_container_id") or "") for item in extract_rows]
    if len(extract_ids) != len(set(extract_ids)):
        errors.append("content_extract_source_ids_duplicate")
    extract_by_id = {str(item.get("source_container_id") or ""): item for item in extract_rows}
    ready_ids: list[str] = []
    confirmed_wechat_boundaries = 0
    for source_id in selected_ids:
        record = extract_by_id.get(source_id)
        if record is None:
            errors.append(f"content_extract_missing:{source_id}")
            continue
        status = str(record.get("status") or "")
        if status != "parsed":
            if report_mode == "final":
                errors.append(f"content_extract_not_ready:{source_id}:{status}")
            else:
                warnings.append(f"content_extract_not_ready:{source_id}:{status}")
            continue
        origin = Path(str(record.get("origin_path") or ""))
        artifact = Path(str(record.get("artifact_path") or ""))
        if not origin.is_file() or not artifact.is_file():
            errors.append(f"content_extract_file_missing:{source_id}")
            continue
        if file_sha256(origin) != record.get("origin_sha256"):
            errors.append(f"origin_hash_mismatch:{source_id}")
        if file_sha256(artifact) != record.get("artifact_sha256"):
            errors.append(f"artifact_hash_mismatch:{source_id}")
        inventory_hash = (inventory_by_id.get(source_id) or {}).get("sha256")
        if inventory_hash and inventory_hash != record.get("origin_sha256"):
            errors.append(f"inventory_origin_hash_mismatch:{source_id}")
        if record.get("truncated"):
            message = f"full_body_truncated:{source_id}"
            if report_mode == "final":
                errors.append(message)
            else:
                warnings.append(message)
        boundary = record.get("body_boundary") or {}
        if boundary.get("profile") == "wechat_archive":
            if boundary.get("status") not in {"confirmed_markers", "confirmed_js_content"} or boundary.get("requires_manual_confirmation"):
                message = f"wechat_body_boundary_unconfirmed:{source_id}:{boundary.get('status')}"
                if report_mode == "final":
                    errors.append(message)
                else:
                    warnings.append(message)
            else:
                confirmed_wechat_boundaries += 1
        inputs.extend([artifact_record(f"origin:{source_id}", origin), artifact_record(f"body:{source_id}", artifact)])
        ready_ids.append(source_id)

    review_by_id: dict[str, Any] = {}
    author_scope_confirmed = False
    reviewed_ids: list[str] = []
    content_evidence_ids: list[str] = []
    required_dimensions = list(review.get("required_dimensions") or [])
    if review:
        if review.get("route") != "same_author_content":
            errors.append(f"review_route_mismatch:{review.get('route')}")
        scope = review.get("author_scope") or {}
        scope_ids = [str(value) for value in scope.get("source_container_ids", [])]
        author_scope_confirmed = scope.get("status") == "confirmed" and bool(scope.get("basis")) and set(selected_ids).issubset(set(scope_ids))
        if report_mode == "final" and not author_scope_confirmed:
            errors.append("author_scope_not_confirmed")
        articles = review.get("articles") or []
        article_ids = [str(item.get("source_container_id") or "") for item in articles]
        if len(article_ids) != len(set(article_ids)):
            errors.append("review_article_ids_duplicate")
        review_by_id = {str(item.get("source_container_id") or ""): item for item in articles}
        for source_id in selected_ids:
            article = review_by_id.get(source_id)
            if article is None:
                errors.append(f"article_review_missing:{source_id}")
                continue
            body = article.get("body") or {}
            if body.get("artifact_sha256") != (extract_by_id.get(source_id) or {}).get("artifact_sha256"):
                errors.append(f"article_review_body_hash_mismatch:{source_id}")
            dimension_rows = article.get("dimensions", [])
            dimension_ids = [str(item.get("id") or "") for item in dimension_rows]
            if len(dimension_ids) != len(set(dimension_ids)):
                errors.append(f"article_dimension_ids_duplicate:{source_id}")
            dimensions = {str(item.get("id") or ""): str(item.get("status") or "") for item in dimension_rows}
            for dimension in dimension_rows:
                dimension_id = str(dimension.get("id") or "")
                if dimension.get("status") == "reviewed" and not (str(dimension.get("note") or "").strip() or dimension.get("evidence_ids")):
                    message = f"article_dimension_review_missing_note:{source_id}:{dimension_id}"
                    if report_mode == "final":
                        errors.append(message)
                    else:
                        warnings.append(message)
            missing_dimensions = [dimension for dimension in required_dimensions if dimensions.get(dimension) not in FINAL_DIMENSION_STATES]
            if article.get("review_status") == "reviewed" and not missing_dimensions:
                reviewed_ids.append(source_id)
            elif report_mode == "final":
                errors.append(f"article_review_incomplete:{source_id}:{'|'.join(missing_dimensions) or article.get('review_status')}")
            else:
                warnings.append(f"article_review_incomplete:{source_id}")
            has_content_evidence = any(
                str(dimension.get("id") or "") in required_dimensions
                and str(dimension.get("id") or "") not in NON_CONTENT_DIMENSIONS
                and dimension.get("status") == "reviewed"
                and bool(str(dimension.get("note") or "").strip() or dimension.get("evidence_ids"))
                for dimension in dimension_rows
            )
            if has_content_evidence:
                content_evidence_ids.append(source_id)
    elif report_mode != "final":
        warnings.append("same_author_review_manifest_missing")

    visual_plan = review.get("visual_review_plan") or {}
    visual_state = str(visual_plan.get("status") or "not_declared")
    visual_scope = str(visual_plan.get("scope") or "not_declared")
    if review and "visual_layout" in required_dimensions and report_mode == "final" and visual_state not in FINAL_VISUAL_STATES:
        errors.append(f"visual_review_plan_incomplete:{visual_state}")
    if visual_state == "complete" and visual_scope in {"representative", "full_selected"}:
        if not visual_plan.get("selection_rule"):
            errors.append("visual_selection_rule_missing")
        reviewed_visuals = int(visual_plan.get("reviewed_items") or 0)
        eligible_visuals = int(visual_plan.get("eligible_items") or 0)
        if reviewed_visuals < 1 or reviewed_visuals > eligible_visuals:
            errors.append(f"visual_review_counts_invalid:{reviewed_visuals}/{eligible_visuals}")
        if visual_scope == "representative" and reviewed_visuals < eligible_visuals and not visual_plan.get("bias_warning"):
            errors.append("representative_visual_bias_warning_missing")
        if not paths["visual_inventory"].is_file():
            errors.append("visual_inventory_missing_for_completed_review")
        else:
            visual_data = load_json(paths["visual_inventory"])
            summary = visual_data.get("summary") or {}
            if int(summary.get("semantic_reviewed_images") or 0) < reviewed_visuals:
                errors.append("visual_inventory_review_count_below_plan")
            if int(summary.get("source_mapped_images") or 0) < reviewed_visuals:
                errors.append("visual_inventory_mapping_count_below_plan")

    required_content_dimensions = [dimension for dimension in required_dimensions if dimension not in NON_CONTENT_DIMENSIONS]
    if report_mode == "final" and required_content_dimensions and len(content_evidence_ids) < 2:
        errors.append(f"insufficient_reviewed_articles_for_content_comparison:{len(content_evidence_ids)}")
    elif report_mode != "final" and len(ready_ids) < 2:
        errors.append(f"insufficient_ready_articles_for_comparison:{len(ready_ids)}")
    review_process_complete = report_mode == "final" and set(reviewed_ids) == set(selected_ids) and author_scope_confirmed
    valid = not errors
    scope_complete = bool(valid and review_process_complete)
    performance_available = int(((inventory.get("summary") or {}).get("by_evidence_role") or {}).get("performance_table") or 0) > 0
    return {
        "gate_version": "same-author/2.0",
        "route": "same_author_content",
        "valid": valid,
        "report_mode": report_mode,
        "report_depth": depth,
        "report_eligible": valid,
        "scope_complete": scope_complete,
        "inputs": inputs,
        "capabilities": {
            "content_pattern_analysis": len(content_evidence_ids) >= 2,
            "visual_claim_scope": "full_selected" if visual_state == "complete" and visual_scope == "full_selected" else "representative_only" if visual_state == "complete" and visual_scope == "representative" else "none",
            "performance_effect_analysis": performance_available,
        },
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "checks": {
            "eligible_articles": eligible_count,
            "selected_articles": selected_count,
            "ready_body_artifacts": len(ready_ids),
            "reviewed_articles": len(reviewed_ids),
            "content_evidence_articles": len(content_evidence_ids),
            "review_process_complete": review_process_complete,
            "confirmed_wechat_boundaries": confirmed_wechat_boundaries,
            "author_scope_confirmed": author_scope_confirmed,
            "sample_strategy": sample.get("strategy"),
            "visual_review_status": visual_state,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a same-author Data Lens run before contract 2.3 rendering.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--report-mode", choices=("preliminary", "final"), required=True)
    parser.add_argument("--depth", choices=("brief", "standard", "deep"), required=True)
    parser.add_argument("--extract-manifest", type=Path)
    parser.add_argument("--review-manifest", type=Path)
    parser.add_argument("--visual-inventory", type=Path)
    parser.add_argument("--visual-mapping", type=Path)
    parser.add_argument("--json-report", type=Path, required=True)
    args = parser.parse_args()
    result = validate_same_author_run(
        args.workspace,
        args.report_mode,
        args.depth,
        extract_manifest=args.extract_manifest,
        review_manifest=args.review_manifest,
        visual_inventory=args.visual_inventory,
        visual_mapping=args.visual_mapping,
    )
    write_json(args.json_report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
