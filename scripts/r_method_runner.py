from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from _common import atomic_output_path, ensure_output_not_source, exclusive_output_reservation, file_sha256, load_json
from runtime_discovery import probe_r_runtime, r_subprocess_environment


SKILL_ROOT = Path(__file__).resolve().parent.parent
REGISTERED_R_ROOT = (SKILL_ROOT / "methods" / "implementations" / "r").resolve()


Runner = Callable[..., subprocess.CompletedProcess[str]]


def probe(rscript: str | Path | None = None, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    return probe_r_runtime(rscript, runner=runner)


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


def run_method(
    script: Path,
    input_path: Path,
    output_path: Path,
    *,
    timeout: int = 120,
    rscript: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    registered = _registered_script(script)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    ensure_output_not_source(output_path, [registered, input_path])
    if timeout < 1 or timeout > 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    runtime = probe(rscript, runner=runner)
    if not runtime["available"]:
        raise RuntimeError(runtime.get("diagnostic") or "Rscript is unavailable; Data Lens does not install R automatically")
    input_hash_before = file_sha256(input_path)
    with exclusive_output_reservation(output_path, label="R output"):
        with atomic_output_path(output_path) as temporary:
            completed = runner(
                [runtime["command"], "--vanilla", str(registered), str(input_path.resolve()), str(temporary.resolve())],
                cwd=SKILL_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=r_subprocess_environment(),
            )
            if completed.returncode:
                raise RuntimeError(f"R method failed with exit {completed.returncode}: {completed.stderr.strip()[:1000]}")
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("R method completed without a result file")
            payload = load_json(temporary)
            errors = validate_result(payload)
            if errors:
                raise ValueError("; ".join(errors))
            if file_sha256(input_path) != input_hash_before:
                raise RuntimeError("R input changed during execution; result was not published")
    return {
        "contract_version": "data-lens-r-run/1.0",
        "runtime": {key: runtime.get(key) for key in ("command", "discovery_source", "version", "utf8_locale_sanitized")},
        "runtime_messages": completed.stderr.strip()[:1000] if completed.stderr.strip() else None,
        "script_sha256": file_sha256(registered),
        "input_sha256": input_hash_before,
        "output_sha256": file_sha256(output_path),
        "result": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a registered optional R method without installing R or packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--rscript", help="Explicit existing Rscript file or R installation directory")
    run = subparsers.add_parser("run")
    run.add_argument("--script", type=Path, required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("--rscript", help="Explicit existing Rscript file or R installation directory")
    args = parser.parse_args()
    if args.command == "probe":
        payload = probe(args.rscript)
    else:
        payload = run_method(args.script, args.input, args.output, timeout=args.timeout, rscript=args.rscript)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
