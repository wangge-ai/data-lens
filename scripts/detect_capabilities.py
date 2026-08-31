from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from typing import Any


PYTHON_MODULES = {
    "pandas": "tabular",
    "openpyxl": "excel",
    "duckdb": "large_tabular",
    "pyarrow": "columnar",
    "PIL": "image",
    "sentence_transformers": "semantic_embeddings",
    "chromadb": "chroma_vector_store",
    "qdrant_client": "qdrant_vector_store",
}

EXECUTABLES = {
    "Rscript": "r_runtime",
    "ffprobe": "audio_video_metadata",
    "pdftoppm": "pdf_rendering",
    "tesseract": "ocr",
}


def detect() -> dict[str, Any]:
    optional_python = {
        capability: {"available": importlib.util.find_spec(module) is not None, "module": module}
        for module, capability in PYTHON_MODULES.items()
    }
    executables = {
        capability: {"available": shutil.which(executable) is not None, "command": executable}
        for executable, capability in EXECUTABLES.items()
    }
    return {
        "contract_version": "data-lens-capabilities/1.0",
        "core": {"python_standard_library": {"available": True}},
        "optional_python": optional_python,
        "optional_executables": executables,
        "policy": {
            "auto_install": False,
            "remote_services_enabled_by_default": False,
            "missing_optional_capability": "degrade_or_report_gap",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect optional Data Lens capabilities without installing anything.")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    print(json.dumps(detect(), ensure_ascii=False, indent=None if args.compact else 2))


if __name__ == "__main__":
    main()
