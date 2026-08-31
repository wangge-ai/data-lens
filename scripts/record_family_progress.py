from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


def apply_feedback(state: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    rows = feedback.get("families", []) if isinstance(feedback, dict) else feedback
    if not isinstance(rows, list):
        raise ValueError("feedback must be a list or an object containing families")
    by_label = {str(item.get("label")): item for item in state.get("families", [])}
    batches = {str(item.get("batch_id")): item for item in state.get("batches", [])}
    for row in rows:
        label = str(row.get("family") or "")
        family = by_label.get(label)
        if family is None:
            raise ValueError(f"feedback references unknown family: {label}")
        batch_id = str(row.get("batch_id") or "")
        if not batch_id:
            raise ValueError(f"batch_id is required: {label}")
        if batch_id not in batches:
            raise ValueError(f"feedback references unknown batch: {batch_id}")
        batch = batches[batch_id]
        if str(batch.get("family") or "") != label:
            raise ValueError(f"batch does not belong to family: {batch_id}:{label}")
        new_information = row.get("new_information") or []
        if not isinstance(new_information, list):
            raise ValueError(f"new_information must be a list: {label}")
        batch_sources = {str(value) for value in batch.get("source_container_ids", [])}
        reviewed_now = {str(value) for value in row.get("reviewed_source_ids", [])}
        excluded_now = {str(value) for value in row.get("excluded_source_ids", [])}
        if reviewed_now & excluded_now:
            raise ValueError(f"source cannot be both reviewed and excluded: {label}")
        if not (reviewed_now | excluded_now).issubset(batch_sources):
            raise ValueError(f"feedback source is outside batch: {batch_id}")
        reviewed = {str(value) for value in family.get("reviewed_source_ids", [])}
        reviewed.update(reviewed_now)
        excluded = {str(value) for value in family.get("excluded_source_ids", [])}
        excluded.update(excluded_now)
        if reviewed & excluded:
            raise ValueError(f"source cannot be both reviewed and excluded across batches: {label}")
        family["reviewed_source_ids"] = sorted(reviewed)
        family["excluded_source_ids"] = sorted(excluded)
        family["processed_count"] = len(reviewed)
        family["excluded_count"] = len(excluded)
        history = family.setdefault("new_information_history", [])
        if any(str(item.get("batch_id") or "") == batch_id for item in history):
            raise ValueError(f"feedback already recorded for batch: {batch_id}")
        history.append({
            "batch_id": batch_id,
            "lane": str(batch.get("lane") or "unclassified"),
            "comparison_key": str(row.get("comparison_key") or batch.get("lane") or "unclassified"),
            "new_information": new_information,
            "added_new_information": bool(new_information),
            "note": str(row.get("note") or ""),
        })
        family["status"] = "reviewed"
        batch["status"] = "completed"
        if family.get("eligible_count_known", True) and family["processed_count"] + family["excluded_count"] >= int(family.get("eligible_count") or 0):
            family["expansion_status"] = "full_census_complete"
            family["stability_basis"] = {"mode": "full_census"}
        else:
            family_batches = [item for item in batches.values() if str(item.get("family") or "") == label]
            required_lanes = sorted({str(item.get("lane") or "unclassified") for item in family_batches})
            covered_lanes = sorted({str(item.get("lane") or "unclassified") for item in history})
            comparable: dict[str, list[dict[str, Any]]] = {}
            for item in history:
                comparable.setdefault(str(item.get("comparison_key") or item.get("lane") or "unclassified"), []).append(item)
            stable_key = None
            stable_batches: list[str] = []
            for key, items in comparable.items():
                if len(items) >= 2 and not items[-1]["added_new_information"] and not items[-2]["added_new_information"]:
                    stable_key = key
                    stable_batches = [str(items[-2]["batch_id"]), str(items[-1]["batch_id"])]
                    break
            lanes_covered = set(required_lanes).issubset(set(covered_lanes))
            family["stability_basis"] = {
                "mode": "comparable_batches",
                "required_lanes": required_lanes,
                "covered_lanes": covered_lanes,
                "stable_comparison_key": stable_key,
                "no_new_batch_ids": stable_batches,
            }
            if lanes_covered and stable_key:
                family["expansion_status"] = "stable_two_batches"
            else:
                family["expansion_status"] = "pilot_complete_needs_expansion"
    selected = [item for item in state.get("families", []) if int(item.get("selected_count") or 0) > 0]
    unfinished_batches = [item for item in state.get("batches", []) if item.get("status") not in {"completed", "reused", "excluded"}]
    state.setdefault("stages", {})["semantic_review"] = "completed" if not unfinished_batches else "in_progress"
    if any(item.get("expansion_status") not in {"full_census_complete", "stable_two_batches"} for item in selected):
        state["stages"]["report"] = "pending"
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Record family batch feedback and compute full-census/stable-two-batch states.")
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = apply_feedback(load_json(args.run_state), load_json(args.feedback))
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "stable": sum(1 for item in result.get("families", []) if item.get("expansion_status") in {"full_census_complete", "stable_two_batches"}),
        "families": len(result.get("families", [])),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
