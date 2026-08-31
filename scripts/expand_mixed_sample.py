from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from plan_batches import build_run_state
from select_samples import provisional_family, selectable_sources


STABLE = {"full_census_complete", "stable_two_batches"}


def expand(inventory: dict[str, Any], plan: dict[str, Any], sample: dict[str, Any], state: dict[str, Any], per_family: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if per_family < 1:
        raise ValueError("per_family must be positive")
    sources, _ = selectable_sources(inventory)
    selected = list(sample.get("selected", []))
    selected_ids = {str(item.get("source_container_id")) for item in selected}
    unstable = {str(item.get("label")) for item in state.get("families", []) if int(item.get("selected_count") or 0) > 0 and item.get("expansion_status") not in STABLE}
    candidates: dict[str, list[dict[str, Any]]] = {}
    for item in sources:
        family = provisional_family(item)
        if family in unstable and str(item.get("source_container_id")) not in selected_ids:
            candidates.setdefault(family, []).append({**item, "provisional_family": family})
    added: list[dict[str, Any]] = []
    for family in sorted(unstable):
        ordered = sorted(candidates.get(family, []), key=lambda item: (str(item.get("top_level_bucket") or ""), str(item.get("path") or "")))
        for item in ordered[:per_family]:
            selected.append(item)
            selected_ids.add(str(item.get("source_container_id")))
            added.append(item)
    sample["selected"] = selected
    sample["selected_count"] = len(selected)
    sample["requested_count"] = len(selected)
    eligible_counts = Counter(provisional_family(item) for item in sources)
    selected_counts = Counter(str(item.get("provisional_family") or provisional_family(item)) for item in selected)
    sample["family_coverage"] = [
        {"family": family, "eligible_count": eligible, "selected_count": selected_counts.get(family, 0), "coverage_status": "full" if selected_counts.get(family, 0) == eligible else "partial" if selected_counts.get(family, 0) else "not_selected"}
        for family, eligible in sorted(eligible_counts.items())
    ]
    sample.setdefault("expansion_history", []).append({
        "added_count": len(added),
        "added_source_ids": [str(item.get("source_container_id")) for item in added],
        "per_family": per_family,
        "families": sorted(unstable),
    })
    next_state = build_run_state(plan, inventory, sample, int(state.get("batch_size") or per_family), state)
    return sample, next_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Add the next source batch for every unstable mixed-corpus family.")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--per-family", type=int, default=8)
    parser.add_argument("--sample-output", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    args = parser.parse_args()
    sample, state = expand(load_json(args.inventory), load_json(args.plan), load_json(args.sample), load_json(args.run_state), args.per_family)
    write_json(args.sample_output, sample)
    write_json(args.state_output, state)
    print(json.dumps({"selected": sample["selected_count"], "run_id": state["run_id"], "batches": len(state["batches"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
