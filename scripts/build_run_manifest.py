from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, file_sha256, guard_cli_output, write_json


GROUP_ARGUMENTS = {
    "sources": "source",
    "deterministic_artifacts": "deterministic_artifact",
    "ledgers": "ledger",
    "deliverables": "deliverable",
    "implementations": "implementation",
    "historical_artifacts": "historical_artifact",
}


def expand_files(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_dir():
            expanded.extend(sorted(item for item in resolved.rglob("*") if item.is_file()))
        elif resolved.is_file():
            expanded.append(resolved)
        else:
            raise ValueError(f"manifest input does not exist: {path}")
    unique: dict[str, Path] = {}
    for path in expanded:
        unique.setdefault(str(path).casefold(), path)
    return list(unique.values())


def display_path(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def file_entries(paths: list[Path], base: Path, group: str) -> list[dict[str, Any]]:
    entries = []
    for path in expand_files(paths):
        entry: dict[str, Any] = {
            "path": display_path(path, base),
            "sha256": file_sha256(path),
        }
        if group == "deliverables":
            entry.update({"artifact_status": "current", "release_status": "releasable"})
        elif group == "historical_artifacts":
            entry.update({"artifact_status": "historical", "release_status": "blocked"})
        entries.append(entry)
    return entries


def parse_method(value: str) -> dict[str, str]:
    method_id, separator, version = value.partition("@")
    if not separator or not method_id.strip() or not version.strip():
        raise ValueError(f"method must use id@version: {value}")
    return {"id": method_id.strip(), "version": version.strip()}


def build_manifest(
    base: Path,
    groups: dict[str, list[Path]],
    methods: list[str],
    warnings: list[str] | None = None,
    analysis_status: str = "complete",
    artifact_status: str = "current",
    release_status: str = "releasable",
) -> dict[str, Any]:
    return {
        "manifest_version": "1.0",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "analysis_status": analysis_status,
        "artifact_status": artifact_status,
        "release_status": release_status,
        **{
            group: file_entries(groups.get(group, []), base, group)
            for group in GROUP_ARGUMENTS
        },
        "methods": [parse_method(value) for value in methods],
        "warnings": list(warnings or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the canonical bound run_manifest.json consumed by the existing validator."
    )
    parser.add_argument("--output", type=Path, required=True)
    for group, argument in GROUP_ARGUMENTS.items():
        parser.add_argument(f"--{argument.replace('_', '-')}", type=Path, action="append", default=[])
    parser.add_argument("--method", action="append", required=True, help="Method id and version as id@version")
    parser.add_argument("--warning", action="append", default=[])
    parser.add_argument("--analysis-status", default="complete")
    parser.add_argument("--artifact-status", default="current")
    parser.add_argument("--release-status", default="releasable")
    args = parser.parse_args()
    output = args.output.resolve()
    base = output.parent
    groups = {
        group: list(getattr(args, argument))
        for group, argument in GROUP_ARGUMENTS.items()
    }
    all_inputs = [path for paths in groups.values() for path in paths]
    guard_cli_output(parser, output, all_inputs)
    if output.name != "run_manifest.json":
        parser.error("--output filename must be run_manifest.json")
    if output in expand_files(all_inputs):
        parser.error("run_manifest.json cannot bind itself")
    try:
        payload = build_manifest(
            base,
            groups,
            args.method,
            args.warning,
            args.analysis_status,
            args.artifact_status,
            args.release_status,
        )
    except ValueError as exc:
        parser.error(str(exc))
    write_json(output, payload)
    print(json.dumps({
        "groups": {group: len(payload[group]) for group in GROUP_ARGUMENTS},
        "methods": len(payload["methods"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
