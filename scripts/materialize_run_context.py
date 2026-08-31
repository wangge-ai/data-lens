from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, file_sha256, read_text_fallback, write_json


def inspect_method(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    text, encoding = read_text_fallback(resolved)
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
        "line_count": len(text.splitlines()),
        "encoding": encoding,
        "loaded": True,
    }


def inspect_artifact(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    with resolved.open("rb") as handle:
        handle.read(1)
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
        "loaded": True,
    }


def build_context(route: str, depth: str, methods: list[Path], artifacts: list[Path], steps: list[str] | None = None) -> dict[str, Any]:
    if depth not in {"brief", "standard", "deep"}:
        raise ValueError(f"invalid depth: {depth}")
    if not methods:
        raise ValueError("at least one method reference is required")
    for path in methods + artifacts:
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "context_version": "2.0",
        "created_at": datetime.now().astimezone().isoformat(),
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "route": route,
        "report_depth": depth,
        "pipeline_steps": list(dict.fromkeys([*(steps or []), "materialize_run_context.py"])),
        "method_loads": [inspect_method(path) for path in methods],
        "artifact_inputs": [inspect_artifact(path) for path in artifacts],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read and hash the method and artifact context used by a Data Lens run.")
    parser.add_argument("--route", required=True)
    parser.add_argument("--depth", choices=("brief", "standard", "deep"), required=True)
    parser.add_argument("--method-reference", type=Path, action="append", default=[])
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--step", action="append", default=[], help="Previously executed deterministic step to preserve in the run trace.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_context(args.route, args.depth, args.method_reference, args.artifact, args.step)
    write_json(args.output, payload)
    print(json.dumps({"output": str(args.output.resolve()), "methods_loaded": len(payload["method_loads"]), "artifacts_loaded": len(payload["artifact_inputs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
