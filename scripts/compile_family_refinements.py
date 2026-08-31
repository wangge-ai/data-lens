from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import load_json, write_json


VALID_STATUS = {"confirmed", "candidate"}


def family_id(label: str) -> str:
    return "FAM-" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]


def compile_refinements(
    sample: dict[str, Any], decisions: dict[str, Any] | list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = decisions.get("decisions", []) if isinstance(decisions, dict) else decisions
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list or an object containing decisions")
    selected = json.loads(json.dumps(sample.get("selected", []), ensure_ascii=False))
    by_source = {str(item.get("source_container_id")): item for item in selected}
    history = list(sample.get("family_refinement_history") or [])
    seen: set[str] = set()
    for row in rows:
        source_id = str(row.get("source_container_id") or "")
        if source_id not in by_source:
            raise ValueError(f"family refinement references unselected source: {source_id or '<missing>'}")
        if source_id in seen:
            raise ValueError(f"duplicate family refinement: {source_id}")
        seen.add(source_id)
        status = str(row.get("status") or "confirmed")
        if status not in VALID_STATUS:
            raise ValueError(f"invalid family refinement status: {source_id}:{status}")
        target = str(row.get("target_family") or "").strip()
        comparison_unit = str(row.get("comparison_unit") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not target or not comparison_unit or not reason:
            raise ValueError(f"family refinement requires target_family, comparison_unit, and reason: {source_id}")
        item = by_source[source_id]
        previous = str(item.get("provisional_family") or "待识别资料")
        history.append({
            "source_container_id": source_id,
            "from_family": previous,
            "to_family": target,
            "comparison_unit": comparison_unit,
            "status": status,
            "reason": reason,
        })
        if status == "confirmed":
            item["provisional_family"] = target
            item["confirmed_comparison_unit"] = comparison_unit
            item["family_review_status"] = "confirmed"

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        groups[str(item.get("provisional_family") or "待识别资料")].append(item)
    registry = []
    for label, members in sorted(groups.items()):
        units = sorted({str(item.get("confirmed_comparison_unit") or "unconfirmed") for item in members})
        prior_labels = sorted({
            str(entry.get("from_family")) for entry in history
            if entry.get("status") == "confirmed" and entry.get("to_family") == label and entry.get("from_family") != label
        })
        registry.append({
            "family_id": family_id(label),
            "label": label,
            "status": "confirmed" if units != ["unconfirmed"] else "provisional",
            "comparison_units": units,
            "source_container_ids": sorted(str(item.get("source_container_id")) for item in members),
            "supersedes_labels": prior_labels,
        })

    result = json.loads(json.dumps(sample, ensure_ascii=False))
    result["selection_version"] = "1.5"
    result["selected"] = selected
    result["family_refinement_history"] = history
    original_coverage = {str(item.get("family")): item for item in sample.get("family_coverage", [])}
    result["family_coverage"] = []
    for item in registry:
        unchanged = not item["supersedes_labels"] and item["label"] in original_coverage
        previous = original_coverage.get(item["label"], {})
        result["family_coverage"].append({
            "family": item["label"],
            "eligible_count": int(previous.get("eligible_count") or 0) if unchanged else None,
            "selected_count": len(item["source_container_ids"]),
            "eligibility_status": "known" if unchanged else "requires_full_corpus_reclassification",
        })
    return result, {"family_registry_version": "1.0", "families": registry}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed split/merge/rename decisions before rebuilding mixed-corpus batches.")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-sample", type=Path, required=True)
    parser.add_argument("--output-registry", type=Path, required=True)
    args = parser.parse_args()
    sample, registry = compile_refinements(load_json(args.sample), load_json(args.decisions))
    write_json(args.output_sample, sample)
    write_json(args.output_registry, registry)
    print(json.dumps({"sample": str(args.output_sample.resolve()), "registry": str(args.output_registry.resolve()), "families": len(registry["families"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
