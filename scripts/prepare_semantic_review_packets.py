from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from validate_mixed_workspace import read_jsonl


def bounded_value(value: Any, char_limit: int) -> Any:
    if isinstance(value, str) and len(value) > char_limit:
        return value[:char_limit] + "…"
    return value


def sheet_previews(
    workspace: Path, table_reviews: list[dict[str, Any]], row_limit: int, column_limit: int, char_limit: int
) -> dict[str, list[dict[str, Any]]]:
    tables_path = workspace / "tables_screening.json"
    if not tables_path.is_file():
        return {}
    tables = load_json(tables_path)
    sheets_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for workbook in tables.get("files", []):
        workbook_path = str(Path(str(workbook.get("path") or "")).resolve()).lower()
        for sheet in workbook.get("sheets", []):
            sheets_by_key[(workbook_path, str(sheet.get("name") or ""))] = sheet
    result: dict[str, list[dict[str, Any]]] = {}
    for review in table_reviews:
        source_id = str(review.get("source_container_id") or "")
        key = (str(Path(str(review.get("workbook_path") or "")).resolve()).lower(), str(review.get("sheet_name") or ""))
        sheet = sheets_by_key.get(key)
        if not sheet:
            continue
        preview_rows = []
        for row_index, row in enumerate(sheet.get("rows", [])[:row_limit]):
            if isinstance(row, dict):
                limited = {str(key): bounded_value(value, char_limit) for key, value in list(row.items())[:column_limit]}
            elif isinstance(row, list):
                limited = [bounded_value(value, char_limit) for value in row[:column_limit]]
            else:
                limited = bounded_value(row, char_limit)
            preview_rows.append({"row_index": row_index, "values": limited})
        result.setdefault(source_id, []).append({
            "sheet_id": review.get("sheet_id"),
            "sheet_name": review.get("sheet_name"),
            "analysis_role": review.get("analysis_role"),
            "review_status": review.get("review_status"),
            "can_support_claims": review.get("can_support_claims"),
            "decision_reason": review.get("decision_reason"),
            "row_count": review.get("row_count"),
            "preview_rows": preview_rows,
            "preview_truncated": int(review.get("row_count") or 0) > len(preview_rows),
        })
    return result


def build_packets(
    workspace: Path, output_dir: Path, table_preview_rows: int = 8,
    table_preview_columns: int = 12, table_cell_char_limit: int = 200,
) -> dict[str, Any]:
    sample = load_json(workspace / "sample_selection.json")
    state = load_json(workspace / "run_state.json")
    selected = {str(item.get("source_container_id")): item for item in sample.get("selected", [])}
    extract_manifest_path = workspace / "content_extracts" / "manifest.json"
    extracts = load_json(extract_manifest_path).get("records", []) if extract_manifest_path.is_file() else []
    extract_by_id = {str(item.get("source_container_id")): item for item in extracts}
    reviews_path = workspace / "table_reviews.jsonl"
    table_reviews = read_jsonl(reviews_path) if reviews_path.is_file() else []
    table_by_source: dict[str, list[dict[str, Any]]] = {}
    for review in table_reviews:
        table_by_source.setdefault(str(review.get("source_container_id")), []).append(review)
    previews_by_source = sheet_previews(
        workspace, table_reviews, table_preview_rows, table_preview_columns, table_cell_char_limit
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for batch in state.get("batches", []):
        sources = []
        for source_id in batch.get("source_container_ids", []):
            item = selected.get(str(source_id), {})
            sources.append({
                "source_container_id": source_id,
                "title": item.get("title"),
                "origin_path": item.get("path"),
                "evidence_role": item.get("evidence_role"),
                "business_role": item.get("business_role"),
                "provisional_family": item.get("provisional_family"),
                "content_extract": extract_by_id.get(str(source_id)),
                "sheet_reviews": table_by_source.get(str(source_id), []),
                "sheet_previews": previews_by_source.get(str(source_id), []),
                "source_paths": item.get("source_paths", []),
            })
        packet = {
            "semantic_packet_version": "1.0",
            "batch_id": batch.get("batch_id"),
            "family": batch.get("family"),
            "lane": batch.get("lane"),
            "sources": sources,
            "required_output": {
                "atomic_evidence": "每条 evidence_unit 只保留一条 observed_fact，并带原始文件哈希和可机械验证的 locator。",
                "directness": ["direct", "derived", "inferred"],
                "boundaries": "每条证据必须说明不能证明什么。",
                "forbidden": "不得把 evidence_units.jsonl、family_analyses.jsonl、relations.jsonl 或 deep_analysis.json 当直接证据源。",
            },
            "table_preview_policy": {
                "row_limit": table_preview_rows,
                "column_limit": table_preview_columns,
                "cell_char_limit": table_cell_char_limit,
                "boundary": "预览用于语义定向，不代表审阅了预览范围之外的行；正式表格证据仍必须指向 tables_screening.json 的具体行。",
            },
        }
        path = output_dir / f"{batch.get('batch_id')}.json"
        write_json(path, packet)
        index.append({"batch_id": batch.get("batch_id"), "path": str(path.resolve()), "sources": len(sources)})
    payload = {"packet_index_version": "1.0", "packets": index}
    write_json(output_dir / "index.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Package selected mixed-corpus sources for reproducible semantic review.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--table-preview-rows", type=int, default=8)
    parser.add_argument("--table-preview-columns", type=int, default=12)
    parser.add_argument("--table-cell-char-limit", type=int, default=200)
    args = parser.parse_args()
    result = build_packets(
        args.workspace, args.output_dir, args.table_preview_rows,
        args.table_preview_columns, args.table_cell_char_limit,
    )
    print(json.dumps({"output": str((args.output_dir / "index.json").resolve()), "packets": len(result["packets"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
