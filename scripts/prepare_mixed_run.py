from __future__ import annotations

import argparse
import math
from pathlib import Path

from _common import write_json
from build_source_graph import build_graph
from inventory_inputs import collect
from plan_analysis import build_plan
from plan_batches import build_run_state
from select_samples import build_sample
from validate_mixed_workspace import validate_workspace


def recommended_sample_count(canonical_items: int) -> int:
    if canonical_items <= 40:
        return canonical_items
    return min(canonical_items, 60, max(20, math.ceil(math.sqrt(canonical_items) * 4)))


def prepare(
    paths: list[Path], goal: str, output_dir: Path, count: int | None = None,
    batch_size: int = 10, hash_max_mb: int = 64, previous_state: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    managed_names = (
        "inventory.json", "analysis_plan.json", "sample_selection.json", "source_graph.json", "run_state.json",
        "evidence_units.jsonl", "family_analyses.jsonl", "relations.jsonl", "table_reviews.jsonl",
        "source_dispositions.jsonl", "mixed_workspace_validation.json",
    )
    existing = [name for name in managed_names if (output_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"mixed workspace already contains managed artifacts ({', '.join(existing)}); use a new output directory and --previous-state for an incremental run"
        )
    inventory = collect(paths, hash_max_mb)
    plan = build_plan(goal, inventory)
    if plan.get("primary_route") != "mixed_corpus":
        raise ValueError(f"prepare_mixed_run requires mixed_corpus, got {plan.get('primary_route')}")
    canonical_items = int((inventory.get("summary") or {}).get("canonical_items") or 0)
    selected_count = count if count is not None else recommended_sample_count(canonical_items)
    sample = build_sample(inventory, "family_stratified", max(1, selected_count))
    graph = build_graph(inventory)
    previous = None
    if previous_state:
        from _common import load_json

        previous = load_json(previous_state)
    state = build_run_state(plan, inventory, sample, batch_size, previous)

    write_json(output_dir / "inventory.json", inventory)
    write_json(output_dir / "analysis_plan.json", plan)
    write_json(output_dir / "sample_selection.json", sample)
    write_json(output_dir / "source_graph.json", graph)
    write_json(output_dir / "run_state.json", state)
    for name in ("evidence_units.jsonl", "family_analyses.jsonl", "relations.jsonl", "table_reviews.jsonl", "source_dispositions.jsonl"):
        path = output_dir / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    validation = validate_workspace(output_dir, allow_incomplete=True)
    write_json(output_dir / "mixed_workspace_validation.json", validation)
    return {
        "output_dir": str(output_dir.resolve()),
        "route": plan["primary_route"],
        "canonical_items": canonical_items,
        "selected_items": sample["selected_count"],
        "provisional_families": len(sample.get("family_coverage", [])),
        "batches": len(state.get("batches", [])),
        "workspace_valid_for_progress": validation["valid"],
        "warnings": validation["warnings"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a complete, resumable Data Lens mixed-corpus workspace.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--hash-max-mb", type=int, default=64)
    parser.add_argument("--previous-state", type=Path)
    args = parser.parse_args()
    result = prepare(args.paths, args.goal, args.output_dir, args.count, args.batch_size, args.hash_max_mb, args.previous_state)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
