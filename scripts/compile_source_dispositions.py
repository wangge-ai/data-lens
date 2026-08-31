from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from validate_mixed_workspace import read_jsonl


VALID_DISPOSITIONS = {"analyzed", "excluded", "pending"}


def compile_dispositions(
    state: dict[str, Any],
    sample: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    decisions: dict[str, Any] | list[dict[str, Any]],
    strict: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    rows = decisions.get("decisions", []) if isinstance(decisions, dict) else decisions
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list or an object containing decisions")

    selected_ids = {
        str(item.get("source_container_id"))
        for item in sample.get("selected", [])
        if item.get("source_container_id")
    }
    evidence_by_source: dict[str, list[str]] = {}
    for item in evidence_rows:
        source_id = str(item.get("source_container_id") or "")
        evidence_id = str(item.get("evidence_unit_id") or "")
        if source_id and evidence_id:
            evidence_by_source.setdefault(source_id, []).append(evidence_id)

    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every source disposition must be an object")
        source_id = str(row.get("source_container_id") or "")
        if source_id not in selected_ids:
            raise ValueError(f"disposition references unselected source: {source_id or '<missing>'}")
        if source_id in by_source:
            raise ValueError(f"duplicate source disposition: {source_id}")
        disposition = str(row.get("disposition") or "pending")
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"invalid source disposition: {source_id}:{disposition}")
        reason = str(row.get("reason") or "").strip()
        if disposition == "excluded" and not reason:
            raise ValueError(f"excluded source requires reason: {source_id}")
        if disposition == "analyzed" and source_id not in evidence_by_source:
            raise ValueError(f"analyzed source has no compiled evidence: {source_id}")
        by_source[source_id] = {
            "source_container_id": source_id,
            "disposition": disposition,
            "reason": reason,
            "reviewer": str(row.get("reviewer") or ""),
            "evidence_unit_ids": sorted(evidence_by_source.get(source_id, [])),
        }

    missing = sorted(selected_ids - set(by_source))
    if strict and missing:
        raise ValueError("selected sources missing disposition: " + "|".join(missing))
    for source_id in missing:
        by_source[source_id] = {
            "source_container_id": source_id,
            "disposition": "pending",
            "reason": "",
            "reviewer": "",
            "evidence_unit_ids": sorted(evidence_by_source.get(source_id, [])),
        }

    normalized = [by_source[source_id] for source_id in sorted(by_source)]
    analyzed = {item["source_container_id"] for item in normalized if item["disposition"] == "analyzed"}
    excluded = {item["source_container_id"] for item in normalized if item["disposition"] == "excluded"}
    pending = {item["source_container_id"] for item in normalized if item["disposition"] == "pending"}

    result = json.loads(json.dumps(state, ensure_ascii=False))
    result["excluded_sources"] = [
        {"source_container_id": item["source_container_id"], "reason": item["reason"], "reviewer": item["reviewer"]}
        for item in normalized if item["disposition"] == "excluded"
    ]
    for batch in result.get("batches", []):
        members = {str(value) for value in batch.get("source_container_ids", [])}
        if members and members.issubset(analyzed | excluded):
            batch["status"] = "completed" if members & analyzed else "excluded"
            batch["failure_reason"] = None
        elif batch.get("status") not in {"failed", "reused"}:
            batch["status"] = "pending"

    for family in result.get("families", []):
        label = str(family.get("label") or "")
        members = {
            str(source_id)
            for batch in result.get("batches", [])
            if str(batch.get("family") or "") == label
            for source_id in batch.get("source_container_ids", [])
        }
        family_analyzed = sorted(members & analyzed)
        family_excluded = sorted(members & excluded)
        family["reviewed_source_ids"] = family_analyzed
        family["excluded_source_ids"] = family_excluded
        family["processed_count"] = len(family_analyzed)
        family["excluded_count"] = len(family_excluded)
        if members and members.issubset(analyzed | excluded):
            family["status"] = "reviewed"
        elif members:
            family["status"] = "pending"

    stages = result.setdefault("stages", {})
    stages["semantic_review"] = "completed" if selected_ids and not pending and selected_ids.issubset(analyzed | excluded) else "in_progress"
    if stages["semantic_review"] != "completed":
        stages["report"] = "pending"

    summary = {
        "selected": len(selected_ids),
        "analyzed": len(analyzed),
        "excluded": len(excluded),
        "pending": len(pending),
        "missing_decisions_filled_as_pending": len(missing),
    }
    return result, normalized, summary


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile reviewed source dispositions into the mixed-corpus run state.")
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    state, ledger, summary = compile_dispositions(
        load_json(args.run_state), load_json(args.sample), read_jsonl(args.evidence), load_json(args.decisions), args.strict
    )
    write_json(args.state_output, state)
    write_jsonl(args.ledger_output, ledger)
    print(json.dumps({"state": str(args.state_output.resolve()), "ledger": str(args.ledger_output.resolve()), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
