from __future__ import annotations

import argparse
import csv
import importlib.metadata
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from _common import ensure_output_not_source, exclusive_output_reservation, file_sha256, write_json
from multimodal_inventory import image_size


METHOD_ID = "data_lens.tesseract_ocr"
METHOD_VERSION = "0.1.1"
PADDLE_METHOD_ID = "data_lens.paddleocr_local"
PADDLE_METHOD_VERSION = "0.1.0"
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
ALLOWED_PSMS = {3, 4, 6, 11, 12, 13}
DEFAULT_PSMS = (6, 11)
LANGUAGE_SPEC_RE = re.compile(r"^[A-Za-z0-9_/-]+(?:\+[A-Za-z0-9_/-]+)*$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _polygon_bbox(points: Any) -> tuple[list[list[float]], list[float]]:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError("PaddleOCR text line is missing a polygon with at least three points")
    polygon: list[list[float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError("PaddleOCR polygon point must contain x and y")
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("PaddleOCR polygon contains a non-finite coordinate")
        polygon.append([x, y])
    left = min(point[0] for point in polygon)
    top = min(point[1] for point in polygon)
    right = max(point[0] for point in polygon)
    bottom = max(point[1] for point in polygon)
    return polygon, [left, top, right - left, bottom - top]


def _paddle_entries(raw: Any) -> list[tuple[str, float, Any, Any]]:
    if isinstance(raw, dict):
        body = raw.get("res") if isinstance(raw.get("res"), dict) else raw
        texts = body.get("rec_texts")
        scores = body.get("rec_scores")
        polygons = body.get("rec_polys") or body.get("dt_polys")
        angles = body.get("textline_orientation_angles") or []
        if isinstance(texts, list) and isinstance(scores, list) and isinstance(polygons, list):
            if not (len(texts) == len(scores) == len(polygons)):
                raise ValueError("PaddleOCR v3 result has mismatched text, score, and polygon lengths")
            return [(str(text), float(score), polygon, angles[index] if index < len(angles) else None) for index, (text, score, polygon) in enumerate(zip(texts, scores, polygons))]
        nested: list[tuple[str, float, Any, Any]] = []
        for key in ("results", "data", "pages"):
            if key in body:
                nested.extend(_paddle_entries(body[key]))
        return nested
    if isinstance(raw, (list, tuple)):
        if (
            len(raw) >= 2
            and isinstance(raw[0], (list, tuple))
            and len(raw[0]) >= 3
            and isinstance(raw[1], (list, tuple))
            and len(raw[1]) >= 2
            and isinstance(raw[1][0], str)
        ):
            return [(raw[1][0], float(raw[1][1]), raw[0], None)]
        nested: list[tuple[str, float, Any, Any]] = []
        for item in raw:
            nested.extend(_paddle_entries(item))
        return nested
    return []


def normalize_paddle_output(raw: Any) -> dict[str, Any]:
    words: list[dict[str, Any]] = []
    for index, (text, confidence, points, angle) in enumerate(_paddle_entries(raw), start=1):
        token = text.strip()
        if not token:
            continue
        if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
            raise ValueError("PaddleOCR confidence must be finite and between 0 and 1")
        polygon, bbox = _polygon_bbox(points)
        words.append(
            {
                "text": token,
                "confidence": confidence,
                "locator": {"line": index, "polygon": polygon, "bbox": bbox},
                "orientation_angle": angle,
            }
        )
    return {
        "raw_text": "\n".join(word["text"] for word in words),
        "words": words,
        "lines": [
            {"text": word["text"], "mean_confidence": word["confidence"], "locator": word["locator"], "orientation_angle": word["orientation_angle"]}
            for word in words
        ],
        "metrics": {
            "word_count": len(words),
            "character_count": sum(len(word["text"]) for word in words),
            "mean_confidence": round(sum(word["confidence"] for word in words) / len(words), 6) if words else None,
        },
    }


def _paddle_plain(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, str, int, float, bool)) or value is None:
        return value
    candidate = getattr(value, "json", None)
    if callable(candidate):
        candidate = candidate()
    if candidate is not None:
        return candidate
    raise TypeError(f"unsupported PaddleOCR result object: {type(value).__name__}")


def _paddle_worker(source: Path, destination: Path, detection_model: Path, recognition_model: Path, orientation_model: Path | None) -> None:
    from paddleocr import PaddleOCR  # type: ignore

    common = {"lang": "ch"}
    try:
        engine = PaddleOCR(
            **common,
            text_detection_model_dir=str(detection_model.resolve()),
            text_recognition_model_dir=str(recognition_model.resolve()),
            textline_orientation_model_dir=str(orientation_model.resolve()) if orientation_model else None,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=orientation_model is not None,
        )
        api = "predict_v3"
    except TypeError:
        engine = PaddleOCR(
            **common,
            det_model_dir=str(detection_model.resolve()),
            rec_model_dir=str(recognition_model.resolve()),
            cls_model_dir=str(orientation_model.resolve()) if orientation_model else None,
            use_angle_cls=orientation_model is not None,
            show_log=False,
        )
        api = "ocr_v2"
    if api == "predict_v3":
        raw = [_paddle_plain(item) for item in engine.predict(str(source.resolve()))]
    else:
        raw = _paddle_plain(engine.ocr(str(source.resolve()), cls=orientation_model is not None))
    try:
        version = importlib.metadata.version("paddleocr")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    write_json(destination, {"engine_version": version, "api": api, "normalized": normalize_paddle_output(raw)})


def run_paddle_ocr(
    source: Path,
    *,
    detection_model: Path,
    recognition_model: Path,
    orientation_model: Path | None = None,
    timeout: int = 300,
    max_pixels: int = 40_000_000,
    runner: Runner = subprocess.run,
    python_executable: str | None = None,
    module_available: bool | None = None,
) -> dict[str, Any]:
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"not a supported readable image: {source}")
    if timeout < 1 or timeout > 600:
        raise ValueError("PaddleOCR timeout must be between 1 and 600 seconds per image")
    if max_pixels < 1_000_000 or max_pixels > 100_000_000:
        raise ValueError("PaddleOCR max_pixels must be between 1000000 and 100000000")
    dimensions = image_size(source)
    if dimensions and dimensions[0] * dimensions[1] > max_pixels:
        raise ValueError(f"image has {dimensions[0] * dimensions[1]} pixels, above max_pixels={max_pixels}; select bounded regions or tiles")
    model_paths = [detection_model, recognition_model, *([orientation_model] if orientation_model else [])]
    for model_path in model_paths:
        assert model_path is not None
        if not model_path.is_dir() or not any(model_path.iterdir()):
            raise FileNotFoundError(f"explicit non-empty local PaddleOCR model directory is required: {model_path}")
    installed = module_available if module_available is not None else importlib.util.find_spec("paddleocr") is not None and importlib.util.find_spec("paddle") is not None
    if not installed:
        raise RuntimeError("PaddleOCR and PaddlePaddle are unavailable; Data Lens does not install packages or download models automatically")
    source_hash_before = file_sha256(source)
    with tempfile.TemporaryDirectory(prefix="data-lens-paddleocr-") as temporary:
        worker_output = Path(temporary) / "worker-result.json"
        command = [
            python_executable or sys.executable,
            str(Path(__file__).resolve()),
            "__paddle_worker__",
            "--source",
            str(source.resolve()),
            "--output",
            str(worker_output),
            "--detection-model",
            str(detection_model.resolve()),
            "--recognition-model",
            str(recognition_model.resolve()),
        ]
        if orientation_model:
            command.extend(["--orientation-model", str(orientation_model.resolve())])
        environment = os.environ.copy()
        environment.update({"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        completed = runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, env=environment)
        if completed.returncode:
            raise RuntimeError(f"local PaddleOCR worker failed with exit {completed.returncode}: {(completed.stderr or completed.stdout).strip()[:1000]}")
        if not worker_output.is_file():
            raise RuntimeError("local PaddleOCR worker did not create its bounded result")
        worker = json.loads(worker_output.read_text(encoding="utf-8-sig"))
    normalized = worker.get("normalized")
    if not isinstance(normalized, dict):
        raise ValueError("local PaddleOCR worker result is missing normalized evidence")
    usable = int(normalized.get("metrics", {}).get("word_count") or 0) > 0
    source_unchanged = source_hash_before == file_sha256(source)
    candidate = {
        "candidate_id": "paddleocr-local-models",
        "execution_succeeded": usable,
        **normalized,
        "semantic_review_status": "not_reviewed",
        "adoption_status": "not_adopted",
    }
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": source_hash_before,
        "source_unchanged": source_unchanged,
        "source_locator": {"type": "full_frame", "bbox": [0, 0, dimensions[0], dimensions[1]]} if dimensions else {"type": "full_frame", "bbox": None},
        "processing_state": "ocr_complete" if usable and source_unchanged else "source_changed_during_ocr" if not source_unchanged else "ocr_failed_or_empty",
        "semantic_review_status": "not_reviewed",
        "selection_status": "algorithmic_candidate_only" if usable else "no_usable_candidate",
        "algorithmic_preferred_candidate_id": candidate["candidate_id"] if usable else None,
        "candidates": [candidate],
        "layout_capability": "text_lines_with_polygons",
        "table_structure_status": "not_extracted",
        "model_source": "explicit_local_directories",
        "network_download_requested": False,
        "resource_bounds": {"timeout_seconds": timeout, "max_pixels": max_pixels, "observed_pixels": dimensions[0] * dimensions[1] if dimensions else None},
    }
    return {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": PADDLE_METHOD_ID,
        "method_version": PADDLE_METHOD_VERSION,
        "status": "succeeded" if usable and source_unchanged else "failed",
        "results": [result],
        "diagnostics": [{"engine_version": worker.get("engine_version"), "api": worker.get("api"), "timeout_seconds": timeout, "source_unchanged": source_unchanged}],
        "boundaries": [
            "PaddleOCR output is locatable candidate text, not semantic review or an adopted fact.",
            "This adapter extracts text lines and polygons only; table cells and reading order require a separate reviewed structure step.",
            "Local model directories are mandatory and offline hints are set; no model name, installer, retry, or download request is issued by Data Lens.",
        ],
    }


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
    source_hash_before = file_sha256(source)
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
    source_unchanged = source_hash_before == file_sha256(source)
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": source_hash_before,
        "source_unchanged": source_unchanged,
        "source_locator": {"type": "full_frame", "bbox": [0, 0, dimensions[0], dimensions[1]]} if dimensions else {"type": "full_frame", "bbox": None},
        "processing_state": "ocr_complete" if usable and source_unchanged else "source_changed_during_ocr" if not source_unchanged else "ocr_failed_or_empty",
        "semantic_review_status": "not_reviewed",
        "selection_status": "algorithmic_candidate_only" if preferred else "no_usable_candidate",
        "algorithmic_preferred_candidate_id": preferred["candidate_id"] if preferred else None,
        "candidates": candidates,
    }
    return {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "status": "succeeded" if usable and source_unchanged else "failed",
        "results": [result],
        "diagnostics": [*diagnostics, {"source_unchanged": source_unchanged}],
        "boundaries": [
            "OCR output is extracted text candidate evidence, not a semantic review or an adopted finding.",
            "The algorithmic preferred candidate is only a deterministic comparison of bounded OCR runs and must not silently replace raw candidates.",
        ],
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "__paddle_worker__":
        worker = argparse.ArgumentParser()
        worker.add_argument("__paddle_worker__")
        worker.add_argument("--source", type=Path, required=True)
        worker.add_argument("--output", type=Path, required=True)
        worker.add_argument("--detection-model", type=Path, required=True)
        worker.add_argument("--recognition-model", type=Path, required=True)
        worker.add_argument("--orientation-model", type=Path)
        worker_args = worker.parse_args()
        _paddle_worker(worker_args.source, worker_args.output, worker_args.detection_model, worker_args.recognition_model, worker_args.orientation_model)
        return
    parser = argparse.ArgumentParser(description="Run bounded local Tesseract OCR and retain raw candidates, confidence, and pixel locators.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--languages", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, action="append", dest="psms")
    parser.add_argument("--timeout", type=int, default=30, help="Seconds per OCR candidate, from 1 to 120")
    parser.add_argument("--engine", choices=("tesseract", "paddle"), default="tesseract")
    parser.add_argument("--detection-model", type=Path, help="Explicit non-empty local PaddleOCR detection model directory")
    parser.add_argument("--recognition-model", type=Path, help="Explicit non-empty local PaddleOCR recognition model directory")
    parser.add_argument("--orientation-model", type=Path, help="Optional explicit local PaddleOCR text-line orientation model directory")
    parser.add_argument("--max-pixels", type=int, default=40_000_000, help="Reject larger images and require explicit bounded regions or tiles")
    args = parser.parse_args()
    try:
        ensure_output_not_source(args.output, [args.source])
    except ValueError as exc:
        parser.error(str(exc))
    try:
        with exclusive_output_reservation(args.output, label="OCR output"):
            if args.engine == "paddle":
                if not args.detection_model or not args.recognition_model:
                    parser.error("--engine paddle requires --detection-model and --recognition-model")
                payload = run_paddle_ocr(
                    args.source,
                    detection_model=args.detection_model,
                    recognition_model=args.recognition_model,
                    orientation_model=args.orientation_model,
                    timeout=args.timeout,
                    max_pixels=args.max_pixels,
                )
            else:
                payload = run_ocr(args.source, languages=args.languages, psms=tuple(args.psms or DEFAULT_PSMS), timeout=args.timeout)
            write_json(args.output, payload)
    except FileExistsError as exc:
        parser.error(str(exc))
    summary = payload["results"][0]
    print(json.dumps({"output": str(args.output.resolve()), "status": payload["status"], "preferred_candidate": summary["algorithmic_preferred_candidate_id"], "semantic_review_status": summary["semantic_review_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
