from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from typing import Any


PYTHON_MODULES = {
    "pandas": ("tabular", False, False, None),
    "openpyxl": ("excel", True, True, "scripts/parse_tabular_exports.py"),
    "duckdb": ("large_tabular", False, False, None),
    "pyarrow": ("columnar", False, False, None),
    "PIL": ("image", True, True, "scripts/multimodal_inventory.py"),
    "sentence_transformers": ("semantic_embeddings", False, False, None),
    "chromadb": ("chroma_vector_store", False, False, None),
    "qdrant_client": ("qdrant_vector_store", False, False, None),
}

EXECUTABLES = {
    "Rscript": ("r_runtime", True, True, "scripts/r_method_runner.py"),
    "ffprobe": ("audio_video_metadata", True, False, "scripts/multimodal_inventory.py"),
    "pdftoppm": ("pdf_rendering", True, True, "scripts/pdf_evidence.py"),
    "tesseract": ("ocr", True, True, "scripts/ocr_evidence.py"),
}


def capability_record(
    installed: bool,
    locator_name: str,
    locator_value: str,
    wired: bool,
    fixture_validated: bool,
    entrypoint: str | None,
    *,
    production_ready: bool = False,
) -> dict[str, Any]:
    if not installed:
        state = "unavailable"
    elif production_ready:
        state = "production_ready"
    elif fixture_validated:
        state = "fixture_validated"
    elif wired:
        state = "wired"
    else:
        state = "installed_only"
    return {
        "available": installed,
        "installed": installed,
        "wired": wired,
        "fixture_validated": fixture_validated,
        "production_ready": production_ready,
        "state": state,
        locator_name: locator_value,
        "entrypoint": entrypoint,
    }


def detect() -> dict[str, Any]:
    optional_python = {
        capability: capability_record(
            importlib.util.find_spec(module) is not None,
            "module",
            module,
            wired,
            fixture_validated,
            entrypoint,
        )
        for module, (capability, wired, fixture_validated, entrypoint) in PYTHON_MODULES.items()
    }
    executables = {
        capability: capability_record(
            shutil.which(executable) is not None,
            "command",
            executable,
            wired,
            fixture_validated,
            entrypoint,
        )
        for executable, (capability, wired, fixture_validated, entrypoint) in EXECUTABLES.items()
    }
    return {
        "contract_version": "data-lens-capabilities/2.0",
        "core": {
            "python_standard_library": capability_record(
                True,
                "runtime",
                "python_standard_library",
                True,
                True,
                "scripts/data_lens.py",
                production_ready=True,
            )
        },
        "optional_python": optional_python,
        "optional_executables": executables,
        "policy": {
            "auto_install": False,
            "remote_services_enabled_by_default": False,
            "missing_optional_capability": "degrade_or_report_gap",
            "available_means": "dependency_or_executable_is_installed; inspect state fields before claiming workflow support",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect optional Data Lens capabilities without installing anything.")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    print(json.dumps(detect(), ensure_ascii=False, indent=None if args.compact else 2))


if __name__ == "__main__":
    main()
