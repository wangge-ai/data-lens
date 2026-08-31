from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json


VALID_LANES = {"content_text", "performance_table", "tabular_data", "visual_layout", "audience_voice", "temporal_metadata", "audio_video", "source_metadata", "unclassified"}
VALID_DIRECTNESS = {"direct", "derived", "inferred"}


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def compile_evidence(
    sample: dict[str, Any], state: dict[str, Any], extracts: dict[str, Any],
    tables: dict[str, Any], decisions: dict[str, Any],
) -> list[dict[str, Any]]:
    sources = {str(item.get("source_container_id")): item for item in sample.get("selected", [])}
    extract_map = {str(item.get("source_container_id")): item for item in extracts.get("records", [])}
    family_ids = {str(item.get("label")): str(item.get("family_id")) for item in state.get("families", [])}
    table_files = {str(Path(str(item.get("path") or "")).resolve()).lower(): item for item in tables.get("files", [])}
    rows = decisions.get("decisions", []) if isinstance(decisions, dict) else decisions
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list or an object containing decisions")
    output: list[dict[str, Any]] = []
    seen_source_counts: dict[str, int] = {}
    for decision in rows:
        source_id = str(decision.get("source_container_id") or "")
        source = sources.get(source_id)
        if source is None:
            raise ValueError(f"unknown selected source: {source_id}")
        family_label = str(decision.get("family") or source.get("provisional_family") or source.get("business_role") or "")
        family_id = family_ids.get(family_label)
        if not family_id:
            raise ValueError(f"unknown family for evidence: {source_id}:{family_label}")
        observed_fact = str(decision.get("observed_fact") or "").strip()
        cannot_prove = str(decision.get("cannot_prove") or "").strip()
        if not observed_fact or not cannot_prove:
            raise ValueError(f"observed_fact and cannot_prove are required: {source_id}")
        origin = Path(str(source.get("path") or "")).resolve()
        if not origin.is_file():
            raise ValueError(f"origin missing: {origin}")
        kind = str(decision.get("locator_type") or "")
        directness = str(decision.get("directness") or "direct")
        if directness not in VALID_DIRECTNESS:
            raise ValueError(f"unsupported evidence directness: {source_id}:{directness}")
        lane = str(decision.get("lane") or source.get("evidence_role") or "unclassified")
        if lane not in VALID_LANES:
            raise ValueError(f"unsupported evidence lane: {source_id}:{lane}")
        trace: dict[str, Any] = {"origin_path": str(origin), "origin_sha256": file_sha256(origin), "directness": directness}
        source_path: str
        if kind == "text_span":
            extract = extract_map.get(source_id) or {}
            artifact = Path(str(decision.get("artifact_path") or extract.get("artifact_path") or ""))
            if not artifact.is_file():
                raise ValueError(f"text extract missing: {source_id}")
            quote = str(decision.get("quote") or "").strip()
            lines = artifact.read_text(encoding="utf-8-sig").splitlines()
            matches = [index for index, line in enumerate(lines, start=1) if quote and norm(quote) in norm(line)]
            if not matches:
                raise ValueError(f"text quote not found: {source_id}:{quote[:60]}")
            start = matches[0]
            locator = {"type": "text_span", "artifact_path": str(artifact.resolve()), "start_line": start, "end_line": start, "quote": quote}
            trace["artifact_sha256"] = file_sha256(artifact)
            source_path = str(artifact.resolve())
            review_status = "parsed"
        elif kind == "table_extract":
            workbook = table_files.get(str(origin).lower())
            if workbook is None:
                raise ValueError(f"table source not parsed: {source_id}")
            sheet_name = str(decision.get("sheet_name") or "")
            quote = str(decision.get("quote") or "").strip()
            workbook_index = next(index for index, item in enumerate(tables.get("files", [])) if item is workbook)
            sheet_matches = [(index, item) for index, item in enumerate(workbook.get("sheets", [])) if str(item.get("name")) == sheet_name]
            if len(sheet_matches) != 1:
                raise ValueError(f"table sheet not uniquely found: {source_id}:{sheet_name}")
            sheet_index, sheet = sheet_matches[0]
            row_matches = [index for index, row in enumerate(sheet.get("rows", [])) if quote and norm(quote) in norm(json.dumps(row, ensure_ascii=False))]
            if not row_matches:
                raise ValueError(f"table quote not found: {source_id}:{sheet_name}:{quote[:60]}")
            row_index = row_matches[0]
            artifact = Path(str(decision.get("artifact_path") or tables.get("artifact_path") or ""))
            if not artifact.is_file():
                raise ValueError("tables artifact_path must point to the parsed tables JSON")
            locator = {"type": "table_extract", "artifact_path": str(artifact.resolve()), "json_pointer": f"/files/{workbook_index}/sheets/{sheet_index}/rows/{row_index}", "quote": quote}
            trace["artifact_sha256"] = file_sha256(artifact)
            source_path = str(artifact.resolve())
            review_status = "parsed"
        elif kind == "image":
            description = str(decision.get("description") or "").strip()
            if not description:
                raise ValueError(f"image description missing: {source_id}")
            locator = {"type": "image", "path": str(origin), "description": description}
            source_path = str(origin)
            review_status = "semantically_reviewed"
        elif kind == "pdf_pages":
            pages = decision.get("pages")
            if not isinstance(pages, list) or not pages or any(not isinstance(value, int) or value < 1 for value in pages):
                raise ValueError(f"pdf pages missing or invalid: {source_id}")
            locator = {"type": "pdf_pages", "path": str(origin), "pages": sorted(set(pages)), "description": str(decision.get("description") or "")}
            source_path = str(origin)
            review_status = "semantically_reviewed"
        elif kind == "video_frames":
            timestamps = decision.get("timestamps_seconds")
            if not isinstance(timestamps, list) or not timestamps:
                raise ValueError(f"video timestamps missing: {source_id}")
            locator = {"type": "video_frames", "path": str(origin), "timestamps_seconds": timestamps, "description": str(decision.get("description") or "")}
            source_path = str(origin)
            review_status = "semantically_reviewed"
        else:
            raise ValueError(f"unsupported locator_type: {source_id}:{kind}")
        seen_source_counts[source_id] = seen_source_counts.get(source_id, 0) + 1
        evidence_id = "EU-" + hashlib.sha256(f"{source_id}|{seen_source_counts[source_id]}|{observed_fact}".encode("utf-8")).hexdigest()[:12]
        reader_label = str(decision.get("reader_label") or observed_fact).strip()
        if len(reader_label) > 28:
            reader_label = reader_label[:27].rstrip() + "…"
        output.append({
            "evidence_unit_id": evidence_id,
            "source_container_id": source_id,
            "family_id": family_id,
            "lane": lane,
            "unit_type": str(decision.get("unit_type") or "atomic_observation"),
            "review_status": review_status,
            "source_path": source_path,
            "locator": locator,
            "trace": trace,
            "observed_facts": [observed_fact],
            "reader_label": reader_label,
            "interpretations": [str(decision.get("interpretation"))] if decision.get("interpretation") else [],
            "cannot_prove": [cannot_prove],
            "sensitivity": str(decision.get("sensitivity") or "internal"),
            "allowed_use": str(decision.get("allowed_use") or "analysis_only"),
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile reviewed semantic decisions into origin-traceable atomic evidence JSONL.")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--extract-manifest", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tables = load_json(args.tables)
    tables["artifact_path"] = str(args.tables.resolve())
    evidence = compile_evidence(load_json(args.sample), load_json(args.run_state), load_json(args.extract_manifest), tables, load_json(args.decisions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in evidence:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "evidence_units": len(evidence), "covered_sources": len({item['source_container_id'] for item in evidence})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
