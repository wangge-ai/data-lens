from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from _common import ensure_output_not_source, file_sha256, write_json
from multimodal_inventory import image_size


METHOD_ID = "data_lens.tesseract_ocr"
METHOD_VERSION = "0.1.1"
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
ALLOWED_PSMS = {3, 4, 6, 11, 12, 13}
DEFAULT_PSMS = (6, 11)
LANGUAGE_SPEC_RE = re.compile(r"^[A-Za-z0-9_/-]+(?:\+[A-Za-z0-9_/-]+)*$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _integer(value: str, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Tesseract TSV integer in {field}: {value!r}") from exc


def _confidence(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Tesseract TSV confidence: {value!r}") from exc


def parse_tsv(text: str) -> dict[str, Any]:
    if not text.strip():
        return {"raw_text": "", "words": [], "lines": [], "metrics": {"word_count": 0, "character_count": 0, "mean_confidence": None}}
    # Tesseract TSV is tab-delimited but does not implement CSV quoting.
    # A recognized ASCII double quote is ordinary OCR text; allowing csv's
    # default quote handling can swallow all following TSV rows into one token.
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"}
    if not reader.fieldnames or required - set(reader.fieldnames):
        missing = sorted(required - set(reader.fieldnames or []))
        raise ValueError(f"invalid Tesseract TSV header; missing: {', '.join(missing)}")
    words: list[dict[str, Any]] = []
    grouped: dict[tuple[int, int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in reader:
        if _integer(str(row.get("level") or ""), "level") != 5:
            continue
        token = str(row.get("text") or "").strip()
        if not token:
            continue
        confidence = _confidence(str(row.get("conf") or ""))
        locator = {
            "page": _integer(str(row.get("page_num") or ""), "page_num"),
            "block": _integer(str(row.get("block_num") or ""), "block_num"),
            "paragraph": _integer(str(row.get("par_num") or ""), "par_num"),
            "line": _integer(str(row.get("line_num") or ""), "line_num"),
            "word": _integer(str(row.get("word_num") or ""), "word_num"),
            "bbox": [
                _integer(str(row.get("left") or ""), "left"),
                _integer(str(row.get("top") or ""), "top"),
                _integer(str(row.get("width") or ""), "width"),
                _integer(str(row.get("height") or ""), "height"),
            ],
        }
        word = {"text": token, "confidence": confidence, "locator": locator}
        words.append(word)
        grouped[(locator["page"], locator["block"], locator["paragraph"], locator["line"])].append(word)
    lines: list[dict[str, Any]] = []
    for key, line_words in grouped.items():
        left = min(word["locator"]["bbox"][0] for word in line_words)
        top = min(word["locator"]["bbox"][1] for word in line_words)
        right = max(word["locator"]["bbox"][0] + word["locator"]["bbox"][2] for word in line_words)
        bottom = max(word["locator"]["bbox"][1] + word["locator"]["bbox"][3] for word in line_words)
        lines.append(
            {
                "text": " ".join(word["text"] for word in line_words),
                "mean_confidence": round(sum(word["confidence"] for word in line_words) / len(line_words), 4),
                "locator": {"page": key[0], "block": key[1], "paragraph": key[2], "line": key[3], "bbox": [left, top, right - left, bottom - top]},
            }
        )
    raw_text = "\n".join(line["text"] for line in lines)
    mean_confidence = round(sum(word["confidence"] for word in words) / len(words), 4) if words else None
    return {
        "raw_text": raw_text,
        "words": words,
        "lines": lines,
        "metrics": {
            "word_count": len(words),
            "character_count": sum(len(word["text"]) for word in words),
            "mean_confidence": mean_confidence,
        },
    }


def _completed(runner: Runner, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _probe(executable: str, runner: Runner, timeout: int) -> tuple[str, set[str]]:
    version_run = _completed(runner, [executable, "--version"], timeout)
    if version_run.returncode:
        raise RuntimeError(f"Tesseract version probe failed: {(version_run.stderr or version_run.stdout).strip()[:500]}")
    version = (version_run.stdout or version_run.stderr).splitlines()[0].strip()
    language_run = _completed(runner, [executable, "--list-langs"], timeout)
    if language_run.returncode:
        raise RuntimeError(f"Tesseract language probe failed: {(language_run.stderr or language_run.stdout).strip()[:500]}")
    language_lines = (language_run.stdout + "\n" + language_run.stderr).splitlines()
    languages = {line.strip().replace("\\", "/") for line in language_lines if line.strip() and not line.startswith("List of available")}
    return version, languages


def run_ocr(
    source: Path,
    *,
    languages: str = "chi_sim+eng",
    psms: tuple[int, ...] = DEFAULT_PSMS,
    timeout: int = 30,
    runner: Runner = subprocess.run,
    executable: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported OCR source type: {source.suffix}")
    normalized_psms = tuple(dict.fromkeys(psms))
    if not normalized_psms or len(normalized_psms) > 3 or any(psm not in ALLOWED_PSMS for psm in normalized_psms):
        raise ValueError(f"choose one to three supported PSM values: {sorted(ALLOWED_PSMS)}")
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be between 1 and 120 seconds per PSM candidate")
    if not LANGUAGE_SPEC_RE.fullmatch(languages):
        raise ValueError("languages must be a plus-separated list of installed Tesseract language IDs")
    command = executable or shutil.which("tesseract")
    if not command:
        raise RuntimeError("Tesseract is unavailable; install it and make tesseract visible on PATH")
    engine_version, available_languages = _probe(command, runner, timeout)
    requested_languages = [item for item in languages.split("+") if item]
    missing_languages = sorted(set(requested_languages) - available_languages)
    if missing_languages:
        raise ValueError(f"missing Tesseract language data: {', '.join(missing_languages)}")
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = [
        {"engine": engine_version, "requested_languages": requested_languages, "available_language_count": len(available_languages)}
    ]
    for psm in normalized_psms:
        completed = _completed(runner, [command, str(source.resolve()), "stdout", "-l", languages, "--psm", str(psm), "tsv"], timeout)
        candidate: dict[str, Any] = {
            "candidate_id": f"tesseract-psm-{psm}",
            "psm": psm,
            "execution_succeeded": completed.returncode == 0,
            "semantic_review_status": "not_reviewed",
            "adoption_status": "not_adopted",
        }
        if completed.returncode:
            candidate["error"] = (completed.stderr or completed.stdout).strip()[:1000]
        else:
            parsed = parse_tsv(completed.stdout)
            candidate.update(parsed)
            mean_confidence = parsed["metrics"]["mean_confidence"] or 0.0
            character_count = parsed["metrics"]["character_count"]
            bounded_confidence = max(0.0, min(100.0, mean_confidence))
            candidate["algorithmic_score"] = round(bounded_confidence * min(1.0, character_count / 20.0), 4)
            if completed.stderr.strip():
                candidate["engine_messages"] = completed.stderr.strip()[:1000]
        candidates.append(candidate)
        diagnostics.append({"candidate_id": candidate["candidate_id"], "returncode": completed.returncode})
    usable = [candidate for candidate in candidates if candidate.get("execution_succeeded") and candidate.get("metrics", {}).get("word_count", 0) > 0]
    preferred = sorted(
        usable,
        key=lambda candidate: (-float(candidate.get("algorithmic_score") or 0), -int(candidate["metrics"]["character_count"]), int(candidate["psm"])),
    )[0] if usable else None
    dimensions = image_size(source)
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": file_sha256(source),
        "source_locator": {"type": "full_frame", "bbox": [0, 0, dimensions[0], dimensions[1]]} if dimensions else {"type": "full_frame", "bbox": None},
        "processing_state": "ocr_complete" if usable else "ocr_failed_or_empty",
        "semantic_review_status": "not_reviewed",
        "selection_status": "algorithmic_candidate_only" if preferred else "no_usable_candidate",
        "algorithmic_preferred_candidate_id": preferred["candidate_id"] if preferred else None,
        "candidates": candidates,
    }
    return {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "status": "succeeded" if usable else "failed",
        "results": [result],
        "diagnostics": diagnostics,
        "boundaries": [
            "OCR output is extracted text candidate evidence, not a semantic review or an adopted finding.",
            "The algorithmic preferred candidate is only a deterministic comparison of bounded OCR runs and must not silently replace raw candidates.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded local Tesseract OCR and retain raw candidates, confidence, and pixel locators.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--languages", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, action="append", dest="psms")
    parser.add_argument("--timeout", type=int, default=30, help="Seconds per OCR candidate, from 1 to 120")
    args = parser.parse_args()
    try:
        ensure_output_not_source(args.output, [args.source])
    except ValueError as exc:
        parser.error(str(exc))
    payload = run_ocr(args.source, languages=args.languages, psms=tuple(args.psms or DEFAULT_PSMS), timeout=args.timeout)
    write_json(args.output, payload)
    summary = payload["results"][0]
    print(json.dumps({"output": str(args.output.resolve()), "status": payload["status"], "preferred_candidate": summary["algorithmic_preferred_candidate_id"], "semantic_review_status": summary["semantic_review_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
