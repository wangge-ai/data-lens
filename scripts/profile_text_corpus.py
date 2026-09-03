from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, load_json, write_json


DATE_RE = re.compile(r"^\[(\d{8})\d{4}\]")
NUMBERED_SECTION_RE = re.compile(r"^\d{2}$")


def build_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for record in manifest.get("records", []):
        source_id = str(record.get("source_container_id") or "")
        artifact = Path(str(record.get("artifact_path") or ""))
        if record.get("status") != "parsed" or not artifact.is_file():
            failures.append({"source_container_id": source_id, "reason": "parsed_text_artifact_unavailable"})
            continue
        text = artifact.read_text(encoding="utf-8")
        nonempty = [line.strip() for line in text.splitlines() if line.strip()]
        origin_name = Path(str(record.get("origin_path") or "")).name
        date_match = DATE_RE.match(origin_name)
        boundary = record.get("body_boundary") or {}
        rows.append(
            {
                "source_container_id": source_id,
                "title": record.get("title"),
                "publish_date_hint": date_match.group(1) if date_match else None,
                "origin_sha256": record.get("origin_sha256"),
                "artifact_sha256": file_sha256(artifact),
                "character_count": len(text.rstrip("\n")),
                "nonempty_block_count": len(nonempty),
                "numbered_section_marker_count": sum(1 for line in nonempty if NUMBERED_SECTION_RE.fullmatch(line)),
                "body_image_reference_count": len(boundary.get("images") or []),
                "first_nonempty_block": nonempty[0] if nonempty else "",
            }
        )
    image_counts = sorted((int(row["body_image_reference_count"]) for row in rows), reverse=True)
    top_count = min(4, len(image_counts))
    total_images = sum(image_counts)
    return {
        "contract_version": "data-lens-text-corpus-profile/1.0",
        "method": {
            "kind": "deterministic",
            "section_rule": "count nonempty blocks exactly matching two decimal digits",
            "date_rule": "read YYYYMMDD from a leading [YYYYMMDDhhmm] filename token",
            "visual_rule": "count image references inside the confirmed body boundary",
        },
        "summary": {
            "eligible_records": len(manifest.get("records", [])),
            "profiled_records": len(rows),
            "failed_records": len(failures),
            "median_character_count": statistics.median([row["character_count"] for row in rows]) if rows else None,
            "articles_with_numbered_sections": sum(1 for row in rows if row["numbered_section_marker_count"] > 0),
            "numbered_section_markers": sum(row["numbered_section_marker_count"] for row in rows),
            "body_image_references": total_images,
            "articles_without_body_images": sum(1 for row in rows if row["body_image_reference_count"] == 0),
            "top_four_image_references": sum(image_counts[:top_count]),
            "top_four_image_share": round(sum(image_counts[:top_count]) / total_images, 4) if total_images else None,
        },
        "records": rows,
        "failure_ledger": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic structural profile from verified text extracts.")
    parser.add_argument("extract_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.extract_manifest])
    result = build_profile(load_json(args.extract_manifest))
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), **result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
