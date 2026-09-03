from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, load_json, write_json


FILE_GROUPS = (
    "sources",
    "deterministic_artifacts",
    "ledgers",
    "deliverables",
    "implementations",
    "historical_artifacts",
)


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def validate_manifest(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if path.name != "run_manifest.json":
        errors.append("manifest_filename_not_canonical")
    manifest = load_json(path)
    base = path.parent.resolve()

    for field in ("analysis_status", "artifact_status", "release_status"):
        if not manifest.get(field):
            errors.append(f"missing_status_axis:{field}")
    if manifest.get("release_status") == "releasable":
        if manifest.get("analysis_status") not in {"complete", "human_confirmed"}:
            errors.append("release_without_complete_analysis")
        if manifest.get("artifact_status") != "current":
            errors.append("release_without_current_artifact")

    bound_count = 0
    for group in FILE_GROUPS:
        entries = manifest.get(group)
        if not isinstance(entries, list):
            errors.append(f"missing_file_group:{group}")
            continue
        for index, entry in enumerate(entries):
            prefix = f"{group}[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"invalid_file_entry:{prefix}")
                continue
            value = entry.get("path")
            expected = entry.get("sha256")
            if not value or not expected:
                errors.append(f"unbound_file_entry:{prefix}")
                continue
            resolved = _resolve(base, str(value))
            if not resolved.is_file():
                errors.append(f"bound_file_missing:{prefix}")
                continue
            actual = file_sha256(resolved)
            if actual.casefold() != str(expected).casefold():
                errors.append(f"bound_file_hash_mismatch:{prefix}")
            bound_count += 1

    methods = manifest.get("methods")
    if not isinstance(methods, list) or not methods:
        errors.append("methods_missing")
    else:
        for index, method in enumerate(methods):
            if not isinstance(method, dict) or not method.get("id") or not method.get("version"):
                errors.append(f"method_unversioned:{index}")

    current_deliverables = [
        entry for entry in manifest.get("deliverables", [])
        if isinstance(entry, dict)
        and entry.get("artifact_status") == "current"
        and entry.get("release_status") == "releasable"
    ]
    if manifest.get("release_status") == "releasable" and not current_deliverables:
        errors.append("releasable_manifest_has_no_current_deliverable")
    for index, entry in enumerate(manifest.get("historical_artifacts", [])):
        if isinstance(entry, dict) and entry.get("release_status") == "releasable":
            errors.append(f"historical_artifact_marked_releasable:{index}")

    return {"valid": not errors, "errors": errors, "checks": {"bound_files_recomputed": bound_count}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute every file binding and validate three-axis release state in run_manifest.json.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.manifest])
    result = validate_manifest(args.manifest)
    write_json(args.output, result)
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
