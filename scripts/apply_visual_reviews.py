from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


VALID_SEMANTIC = {"not_reviewed", "reviewed"}
VALID_MAPPING = {"unmapped", "candidate", "mapped", "not_applicable"}
VALID_ELIGIBILITY = {"eligible", "excluded", "manual_required"}


def apply(inventory: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    rows = decisions.get("decisions", []) if isinstance(decisions, dict) else decisions
    if not isinstance(rows, list):
        raise ValueError("visual decisions must be a list")
    by_path = {str(Path(str(item.get("path") or "")).resolve()).lower(): item for item in rows if item.get("path")}
    seen: set[str] = set()
    for image in inventory.get("images", []):
        key = str(Path(str(image.get("path") or "")).resolve()).lower()
        decision = by_path.get(key)
        if decision is None:
            continue
        semantic = str(decision.get("semantic_review_status") or "not_reviewed")
        mapping = str(decision.get("source_mapping_status") or image.get("source_mapping_status") or "unmapped")
        prior_eligibility = str(image.get("analysis_eligibility") or "eligible")
        eligibility = str(decision.get("analysis_eligibility") or prior_eligibility)
        if semantic not in VALID_SEMANTIC or mapping not in VALID_MAPPING or eligibility not in VALID_ELIGIBILITY:
            raise ValueError(f"invalid visual decision for {image.get('path')}")
        if prior_eligibility == "excluded" and eligibility != "excluded" and not decision.get("reclassification_reason"):
            raise ValueError(f"excluded visual reclassification requires reason: {image.get('path')}")
        if eligibility == "excluded" and mapping != "not_applicable":
            raise ValueError(f"excluded visual cannot be mapped: {image.get('path')}")
        if eligibility == "manual_required" and mapping == "mapped":
            raise ValueError(f"manual-required visual cannot be marked mapped: {image.get('path')}")
        if semantic == "reviewed" and not decision.get("description"):
            raise ValueError(f"reviewed visual requires description: {image.get('path')}")
        image["semantic_review_status"] = semantic
        image["source_mapping_status"] = mapping
        image["analysis_eligibility"] = eligibility
        image["exclusion_reason"] = decision.get("exclusion_reason") or image.get("exclusion_reason")
        image["reclassification_reason"] = decision.get("reclassification_reason")
        image["semantic_description"] = decision.get("description")
        image["mapped_source_container_id"] = decision.get("source_container_id")
        image["reviewer"] = decision.get("reviewer")
        seen.add(key)
    missing = sorted(set(by_path) - seen)
    if missing:
        raise ValueError("visual decisions reference images outside inventory: " + "|".join(missing))
    images = inventory.get("images", [])
    summary = inventory.setdefault("summary", {})
    summary["semantic_reviewed_images"] = sum(1 for item in images if item.get("semantic_review_status") == "reviewed")
    summary["source_mapped_images"] = sum(1 for item in images if item.get("source_mapping_status") == "mapped")
    summary["semantic_review_pending_images"] = sum(1 for item in images if item.get("analysis_eligibility", "eligible") != "excluded" and item.get("semantic_review_status") != "reviewed")
    summary["analysis_excluded_images"] = sum(1 for item in images if item.get("analysis_eligibility") == "excluded")
    summary["manual_required_images"] = sum(1 for item in images if item.get("analysis_eligibility") == "manual_required")
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply semantic visual decisions and synchronize visual_inventory summary counts.")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = apply(load_json(args.inventory), load_json(args.decisions))
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "semantic_reviewed": result.get("summary", {}).get("semantic_reviewed_images", 0),
        "source_mapped": result.get("summary", {}).get("source_mapped_images", 0),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
