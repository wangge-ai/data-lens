from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from _common import load_json


VALID_ANALYSIS_ROLES = {
    "raw_source_data", "external_market_observation", "internal_performance_data",
    "audience_voice_raw", "audience_voice_synthetic", "coding_template",
    "planning_and_schedule", "requirement_register", "delivery_tracking",
    "method_or_schema", "product_facts", "creative_assets_index", "excluded_unrelated",
}
VALID_REVIEW_STATUS = {"pending", "reviewed", "excluded"}


def sheet_id(path: str, sheet_name: str) -> str:
    return "SHEET-" + hashlib.sha256(f"{Path(path).resolve()}|{sheet_name}".lower().encode("utf-8")).hexdigest()[:12]


def read_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    value = load_json(path)
    rows = value.get("decisions", []) if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list or an object containing decisions")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("sheet_id"):
            raise ValueError("every decision must contain sheet_id")
        result[str(row["sheet_id"])] = row
    return result


def prepare(tables: dict[str, Any], sample: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    selected_by_path = {
        str(Path(str(item.get("path") or "")).resolve()).lower(): item
        for item in sample.get("selected", [])
        if item.get("path")
    }
    records: list[dict[str, Any]] = []
    for workbook in tables.get("files", []):
        normalized = str(Path(str(workbook.get("path") or "")).resolve()).lower()
        selected = selected_by_path.get(normalized)
        if selected is None:
            continue
        for sheet in workbook.get("sheets", []):
            if int(sheet.get("nonempty_cells") or 0) == 0:
                continue
            sid = sheet_id(str(workbook.get("path")), str(sheet.get("name")))
            decision = decisions.get(sid, {})
            review_status = str(decision.get("review_status") or "pending")
            analysis_role = str(decision.get("analysis_role") or "unassigned")
            if review_status not in VALID_REVIEW_STATUS:
                raise ValueError(f"invalid review_status for {sid}: {review_status}")
            if analysis_role != "unassigned" and analysis_role not in VALID_ANALYSIS_ROLES:
                raise ValueError(f"invalid analysis_role for {sid}: {analysis_role}")
            can_support_claims = decision.get("can_support_claims")
            if can_support_claims is None:
                can_support_claims = review_status == "reviewed" and analysis_role not in {"unassigned", "coding_template", "audience_voice_synthetic", "excluded_unrelated"}
            records.append({
                "sheet_id": sid,
                "source_container_id": selected.get("source_container_id"),
                "workbook_path": str(Path(str(workbook.get("path"))).resolve()),
                "workbook_format": workbook.get("format"),
                "sheet_name": sheet.get("name"),
                "row_count": sheet.get("row_count"),
                "nonempty_cells": sheet.get("nonempty_cells"),
                "candidate_role": sheet.get("candidate_role"),
                "analysis_role": analysis_role,
                "review_status": review_status,
                "can_support_claims": bool(can_support_claims),
                "decision_reason": str(decision.get("decision_reason") or ""),
                "source_kind": str(decision.get("source_kind") or "unknown"),
                "metric_scope": str(decision.get("metric_scope") or "not_applicable"),
                "reviewer": str(decision.get("reviewer") or ""),
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or merge the required per-sheet semantic review ledger.")
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = prepare(load_json(args.tables), load_json(args.sample), read_decisions(args.decisions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({
        "output": str(args.output.resolve()), "sheets": len(records),
        "reviewed": sum(1 for item in records if item["review_status"] in {"reviewed", "excluded"}),
        "pending": sum(1 for item in records if item["review_status"] == "pending"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
