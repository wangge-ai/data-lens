from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


IMMUTABLE_KEYS = {"contract_version", "completion_status", "report_depth", "route", "title", "subtitle", "run_gate"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number}:record_not_object")
        rows.append(value)
    return rows


def assemble(scaffold: dict[str, Any], content: dict[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(scaffold)
    for key, value in content.items():
        if key in IMMUTABLE_KEYS:
            if key in scaffold and scaffold[key] != value:
                raise ValueError(f"content cannot override gate-bound field: {key}")
            continue
        if key in {"include_evidence_ids", "include_all_evidence", "evidence", "evidence_family_labels"}:
            continue
        result[key] = value

    by_id = {str(item.get("evidence_unit_id") or ""): item for item in evidence_rows}
    if any(not key for key in by_id):
        raise ValueError("evidence ledger contains a missing evidence_unit_id")
    requested = content.get("include_evidence_ids")
    include_all = bool(content.get("include_all_evidence"))
    if include_all and requested:
        raise ValueError("use include_all_evidence or include_evidence_ids, not both")
    if include_all:
        selected = evidence_rows
    else:
        if not isinstance(requested, list) or not requested:
            raise ValueError("content must provide include_all_evidence=true or a non-empty include_evidence_ids list")
        missing = [str(value) for value in requested if str(value) not in by_id]
        if missing:
            raise ValueError("unknown evidence ids: " + ",".join(missing))
        selected = [by_id[str(value)] for value in requested]
    family_labels = content.get("evidence_family_labels") or {}
    result["evidence"] = []
    for item in selected:
        normalized = dict(item)
        normalized["id"] = str(item.get("evidence_unit_id") or "")
        normalized["source_family"] = str(family_labels.get(str(item.get("family_id") or "")) or item.get("family_id") or "待确认资料族")
        facts = item.get("observed_facts") or []
        normalized["label"] = str(item.get("reader_label") or (facts[0] if facts else "已审核来源证据"))
        result["evidence"].append(normalized)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble reviewed deep-analysis content with origin-traceable evidence.")
    parser.add_argument("--scaffold", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--evidence-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(load_json(args.scaffold), load_json(args.content), read_jsonl(args.evidence_ledger))
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "evidence_items": len(result.get("evidence", []))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
