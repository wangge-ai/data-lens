from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent

COMMANDS = {
    "inventory": "inventory_inputs.py",
    "plan": "plan_analysis.py",
    "profile-text": "profile_text_corpus.py",
    "sample": "select_samples.py",
    "table": "tabular_analysis.py",
    "prepare-mixed": "prepare_mixed_run.py",
    "prepare-operational": "prepare_operational_run.py",
    "analyze-operational": "analyze_operational_facts.py",
    "capabilities": "detect_capabilities.py",
    "vector": "local_vector_index.py",
    "multimodal-inventory": "multimodal_inventory.py",
    "ocr": "ocr_evidence.py",
    "pdf": "pdf_evidence.py",
    "video": "video_evidence.py",
    "transcribe": "transcribe_media.py",
    "r": "r_method_runner.py",
    "validate-adoption": "validate_adoption_ledger.py",
    "validate-analysis": "validate_deep_analysis.py",
    "validate-run": "validate_run_gates.py",
    "render": "render_report.py",
}


def _run(script: str, args: list[str]) -> int:
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT_DIR / script), *args], env=environment, check=False)
    return completed.returncode


def _test() -> int:
    first = _run("test_data_lens.py", [])
    if first:
        return first
    root = SCRIPT_DIR.parent
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-p", "test_*.py"],
        cwd=root,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    return completed.returncode


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print("Data Lens commands:")
        for name in [*sorted(COMMANDS), "test"]:
            print(f"  {name}")
        print("\nRun `python scripts/data_lens.py <command> --help` for command-specific options.")
        return 0
    command, args = sys.argv[1], sys.argv[2:]
    if command == "test":
        return _test()
    script = COMMANDS.get(command)
    if script is None:
        print(f"Unknown Data Lens command: {command}", file=sys.stderr)
        return 2
    return _run(script, args)


if __name__ == "__main__":
    raise SystemExit(main())
