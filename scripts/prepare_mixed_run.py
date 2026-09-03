from __future__ import annotations

import argparse
import math
from pathlib import Path

from _common import guard_cli_output, load_json, write_json
from build_source_graph import build_graph
from inventory_inputs import collect
from plan_analysis import build_plan
from plan_batches import build_run_state
from profile_nested_projects import profile as profile_nested_projects
from select_samples import build_sample
from validate_mixed_workspace import validate_workspace
from validate_corpus_scope_gate import validate as validate_scope_gate


def recommended_sample_count(canonical_items: int) -> int:
    if canonical_items <= 40:
        return canonical_items
    return min(canonical_items, 60, max(20, math.ceil(math.sqrt(canonical_items) * 4)))


def prepare(
    paths: list[Path], goal: str, output_dir: Path, count: int | None = None,
    batch_size: int = 10, hash_max_mb: int = 64, previous_state: Path | None = None,
    scope_gate: dict | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    managed_names = (
        "inventory.json", "analysis_plan.json", "nested_projects.json", "sample_selection.json", "source_graph.json", "run_state.json",
        "evidence_units.jsonl", "family_analyses.jsonl", "relations.jsonl", "table_reviews.jsonl",
        "source_dispositions.jsonl", "mixed_workspace_validation.json",
    )
    existing = [name for name in managed_names if (output_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"mixed workspace already contains managed artifacts ({', '.join(existing)}); use a new output directory and --previous-state for an incremental run"
        )
    inventory = collect(paths, hash_max_mb)
    if scope_gate is None:
        raise ValueError("prepare_mixed_run requires a compiled --scope-gate; classify families and authorize whole-corpus analysis first")
    scope_errors = validate_scope_gate(scope_gate)
    if scope_errors:
        raise ValueError("invalid corpus scope gate: " + "; ".join(scope_errors))
    selection = scope_gate.get("selection") or {}
    if selection.get("scope_type") != "whole_corpus" or scope_gate.get("whole_corpus_synthesis_allowed") is not True:
        raise ValueError("prepare_mixed_run requires an authorized whole-corpus scope with verified cross-family relevance")
    current_source_ids = {
        str(item.get("source_container_id"))
        for item in inventory.get("files", [])
        if item.get("canonical", True) and item.get("source_container_id")
    }
    if set(map(str, scope_gate.get("selected_source_ids") or [])) != current_source_ids:
        raise ValueError("corpus scope gate sources do not match the current inventory; recompile the gate")
    plan = build_plan(goal, inventory, scope_gate)
    if plan.get("primary_route") != "mixed_corpus":
        raise ValueError(f"prepare_mixed_run requires mixed_corpus, got {plan.get('primary_route')}")
    canonical_items = int((inventory.get("summary") or {}).get("canonical_items") or 0)
    nested_projects = profile_nested_projects(inventory)
    selected_count = count if count is not None else recommended_sample_count(canonical_items)
    sample = build_sample(inventory, "family_stratified", max(1, selected_count))
    graph = build_graph(inventory)
    previous = None
    if previous_state:
        previous = load_json(previous_state)
    state = build_run_state(plan, inventory, sample, batch_size, previous)

    write_json(output_dir / "inventory.json", inventory)
    write_json(output_dir / "analysis_plan.json", plan)
    write_json(output_dir / "nested_projects.json", nested_projects)
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
        "nested_projects": nested_projects["project_count"],
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
    parser.add_argument("--scope-gate", type=Path, required=True)
    args = parser.parse_args()
    sources = [*args.paths, args.scope_gate, *([args.previous_state] if args.previous_state else [])]
    for name in (
        "inventory.json", "analysis_plan.json", "nested_projects.json", "sample_selection.json",
        "source_graph.json", "run_state.json", "evidence_units.jsonl", "family_analyses.jsonl",
        "relations.jsonl", "table_reviews.jsonl", "source_dispositions.jsonl", "mixed_workspace_validation.json",
    ):
        guard_cli_output(parser, args.output_dir / name, sources)
    result = prepare(
        args.paths, args.goal, args.output_dir, args.count, args.batch_size,
        args.hash_max_mb, args.previous_state, load_json(args.scope_gate),
    )
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
