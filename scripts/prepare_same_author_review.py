from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


DEFAULT_DIMENSIONS = [
    "topic_selection",
    "audience_problem",
    "title_hook",
    "opening_structure",
    "body_structure",
    "evidence_and_deliverables",
    "writing_style",
    "visual_layout",
    "conversion_design",
    "exceptions",
]

DIMENSION_EXPANSION = {
    "topic_selection": ["topic_selection", "audience_problem"],
    "title_hook": ["title_hook", "opening_structure"],
    "writing_style": ["writing_style"],
    "content_structure": ["body_structure", "evidence_and_deliverables"],
    "visual_layout": ["visual_layout"],
    "conversion_design": ["conversion_design"],
}


def required_dimensions(plan: dict[str, Any]) -> list[str]:
    recognized = [
        str(item.get("id") or "") if isinstance(item, dict) else str(item or "")
        for item in plan.get("recognized_dimensions", [])
    ]
    selected: list[str] = []
    for dimension in recognized:
        selected.extend(DIMENSION_EXPANSION.get(dimension, []))
    if not selected:
        return DEFAULT_DIMENSIONS[:]
    selected.append("exceptions")
    return list(dict.fromkeys(selected))


def prepare(plan: dict[str, Any], sample: dict[str, Any], extracts: dict[str, Any]) -> dict[str, Any]:
    records = extracts.get("records") or []
    extract_by_id = {str(item.get("source_container_id") or ""): item for item in records}
    dimensions = required_dimensions(plan)
    articles = []
    selected_ids = []
    for item in sample.get("selected", []):
        source_id = str(item.get("source_container_id") or "")
        selected_ids.append(source_id)
        extract = extract_by_id.get(source_id) or {}
        boundary = extract.get("body_boundary") or {}
        body_ready = extract.get("status") == "parsed" and not extract.get("truncated")
        articles.append(
            {
                "source_container_id": source_id,
                "title": item.get("title"),
                "body": {
                    "status": "ready" if body_ready else "pending",
                    "scope": "full_body" if not extract.get("truncated") else "excerpt",
                    "boundary_method": extract.get("extraction_method"),
                    "boundary_status": boundary.get("status") or "whole_document",
                    "artifact_path": extract.get("artifact_path"),
                    "artifact_sha256": extract.get("artifact_sha256"),
                    "origin_path": extract.get("origin_path"),
                    "origin_sha256": extract.get("origin_sha256"),
                    "truncated": bool(extract.get("truncated")),
                    "excluded_regions": {
                        "prefix_lines": boundary.get("excluded_prefix_lines"),
                        "suffix_lines": boundary.get("excluded_suffix_lines"),
                    },
                },
                "review_status": "pending",
                "dimensions": [{"id": dimension, "status": "pending", "note": ""} for dimension in dimensions],
            }
        )
    return {
        "review_version": "same-author-review/1.0",
        "route": "same_author_content",
        "author_scope": {
            "scope_id": "",
            "status": "pending_confirmation",
            "basis": "",
            "source_container_ids": selected_ids,
        },
        "required_dimensions": dimensions,
        "visual_review_plan": {
            "scope": "representative" if "visual_layout" in dimensions else "not_required",
            "status": "pending" if "visual_layout" in dimensions else "not_required",
            "selection_rule": "",
            "eligible_items": 0,
            "reviewed_items": 0,
            "covered_source_container_ids": [],
            "bias_warning": "",
        },
        "articles": articles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the semantic review checklist for a same-author Data Lens run.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--extract-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(load_json(args.plan), load_json(args.sample), load_json(args.extract_manifest))
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "articles": len(result["articles"]), "dimensions": len(result["required_dimensions"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
