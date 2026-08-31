from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json


SKILL_ROOT = Path(__file__).resolve().parent.parent
REGISTERED_R_ROOT = (SKILL_ROOT / "methods" / "implementations" / "r").resolve()


def probe() -> dict[str, Any]:
    return {
        "contract_version": "data-lens-r-capability/1.0",
        "available": shutil.which("Rscript") is not None,
        "command": "Rscript",
        "auto_install": False,
    }


def validate_result(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["R result must be a JSON object"]
    if payload.get("contract_version") != "data-lens-method-result/1.0":
        errors.append("contract_version must be data-lens-method-result/1.0")
    if not isinstance(payload.get("method_id"), str) or not payload.get("method_id"):
        errors.append("method_id is required")
    if payload.get("status") not in {"succeeded", "failed", "ineligible"}:
        errors.append("status must be succeeded, failed, or ineligible")
    if not isinstance(payload.get("results"), list):
        errors.append("results must be an array")
    if not isinstance(payload.get("diagnostics"), list):
        errors.append("diagnostics must be an array")
    return errors


def _registered_script(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(REGISTERED_R_ROOT)
    except ValueError as exc:
        raise ValueError(f"R script must be registered under {REGISTERED_R_ROOT}") from exc
    if resolved.suffix.lower() != ".r" or not resolved.is_file():
        raise ValueError("registered R script must be an existing .R file")
    return resolved


def run_method(script: Path, input_path: Path, output_path: Path, *, timeout: int = 120) -> dict[str, Any]:
    executable = shutil.which("Rscript")
    if not executable:
        raise RuntimeError("Rscript is unavailable; Data Lens does not install R automatically")
    registered = _registered_script(script)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [executable, "--vanilla", str(registered), str(input_path.resolve()), str(output_path.resolve())],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"R method failed with exit {completed.returncode}: {completed.stderr.strip()[:1000]}")
    payload = load_json(output_path)
    errors = validate_result(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "contract_version": "data-lens-r-run/1.0",
        "script_sha256": file_sha256(registered),
        "input_sha256": file_sha256(input_path),
        "output_sha256": file_sha256(output_path),
        "result": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a registered optional R method without installing R or packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe")
    run = subparsers.add_parser("run")
    run.add_argument("--script", type=Path, required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.command == "probe":
        payload = probe()
    else:
        payload = run_method(args.script, args.input, args.output, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
