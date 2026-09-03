from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, guard_cli_output, load_json, write_json


PARSER_VERSION = "operational-parser/1.0"
METRIC_VERSION = "operational-metrics/1.0"


def prepare(
    inventory: dict[str, Any],
    previous: dict[str, Any] | None = None,
    parser_version: str = PARSER_VERSION,
    metric_version: str = METRIC_VERSION,
) -> dict[str, Any]:
    old = {
        str(item.get("path")): item
        for item in (previous or {}).get("files", [])
        if item.get("path")
    }
    files: list[dict[str, Any]] = []
    for item in inventory.get("files", []):
        if not item.get("canonical", True):
            continue
        if str(item.get("extension") or "").lower() not in {".csv", ".tsv", ".xls", ".xlsx"}:
            continue
        path = str(item.get("path") or "")
        digest = item.get("sha256")
        prior = old.get(path) or {}
        reusable = bool(
            digest
            and prior.get("sha256") == digest
            and prior.get("parser_version") == parser_version
            and prior.get("metric_version") == metric_version
            and prior.get("status") == "complete"
        )
        reason = "source_and_versions_unchanged" if reusable else (
            "source_hash_unavailable" if not digest else
            "new_source" if not prior else
            "source_changed" if prior.get("sha256") != digest else
            "parser_version_changed" if prior.get("parser_version") != parser_version else
            "metric_version_changed" if prior.get("metric_version") != metric_version else
            "previous_stage_incomplete"
        )
        files.append({
            "path": path,
            "sha256": digest,
            "collection_date_hint": item.get("collection_date_hint"),
            "export_family_key": item.get("repeated_export_family_key"),
            "parser_version": parser_version,
            "metric_version": metric_version,
            "action": "reuse" if reusable else "parse",
            "reason": reason,
            "status": "complete" if reusable else "pending",
        })
    fingerprint_input = [
        [item["path"], item.get("sha256"), parser_version, metric_version]
        for item in files
    ]
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "manifest_version": "1.0",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "route": "repeated_operational_tables",
        "parser_version": parser_version,
        "metric_version": metric_version,
        "stage_fingerprint": fingerprint,
        "files": files,
        "summary": {
            "eligible_files": len(files),
            "reuse": sum(item["action"] == "reuse" for item in files),
            "parse": sum(item["action"] == "parse" for item in files),
            "legacy_xls": sum(str(item["path"]).lower().endswith(".xls") for item in files),
        },
        "incremental_boundary": "Only complete artifacts with identical source hash, parser version, and metric version may be reused. A changed adapter or metric definition requires a new version.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a resumable repeated-operational-table run from a Data Lens inventory.")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parser-version", default=PARSER_VERSION)
    parser.add_argument("--metric-version", default=METRIC_VERSION)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.inventory, *([args.previous_manifest] if args.previous_manifest else [])])
    previous = load_json(args.previous_manifest) if args.previous_manifest else None
    payload = prepare(load_json(args.inventory), previous, args.parser_version, args.metric_version)
    write_json(args.output, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
