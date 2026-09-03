from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from _common import file_sha256, write_json
from multimodal_inventory import image_size
from ocr_evidence import DEFAULT_PSMS, run_ocr


METHOD_ID = "data_lens.pdf_page_ocr"
METHOD_VERSION = "0.1.0"
Runner = Callable[..., subprocess.CompletedProcess[str]]
OcrFunction = Callable[..., dict[str, Any]]


def page_indices(count: int, maximum: int) -> list[int]:
    if count < 1:
        return []
    if maximum < 1:
        raise ValueError("maximum page count must be positive")
    if count <= maximum:
        return list(range(1, count + 1))
    if maximum == 1:
        return [1]
    return sorted({round(index * (count - 1) / (maximum - 1)) + 1 for index in range(maximum)})


def parse_page_spec(spec: str, page_count: int, maximum: int) -> list[int]:
    selected: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            raise ValueError("empty page token")
        if "-" in token:
            left, right = token.split("-", 1)
            start, end = int(left), int(right)
            if start > end:
                raise ValueError(f"descending page range is not allowed: {token}")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(token))
    pages = sorted(selected)
    if not pages or pages[0] < 1 or pages[-1] > page_count:
        raise ValueError(f"pages must be between 1 and {page_count}")
    if len(pages) > maximum:
        raise ValueError(f"selected {len(pages)} pages; maximum is {maximum}")
    return pages


def parse_pdfinfo(text: str) -> int:
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "pages":
            pages = int(value.strip())
            if pages < 1:
                break
            return pages
    raise ValueError("pdfinfo output does not contain a positive Pages value")


def _run(runner: Runner, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _failure(page_number: int | None, stage: str, error: Exception | str) -> dict[str, Any]:
    if isinstance(error, Exception):
        error_type = type(error).__name__
        message = str(error)
    else:
        error_type = "ProcessError"
        message = error
    unit = f"page-{page_number}" if page_number is not None else "document"
    return {
        "failure_id": f"{unit}-{stage}",
        "page_number": page_number,
        "stage": stage,
        "error_type": error_type,
        "message": message[:1000],
        "retry_status": "not_retried",
    }


def build_pdf_evidence(
    source: Path,
    output_dir: Path,
    *,
    max_pages: int = 6,
    page_spec: str | None = None,
    dpi: int = 150,
    run_page_ocr: bool = True,
    languages: str = "chi_sim+eng",
    psms: tuple[int, ...] = DEFAULT_PSMS,
    timeout: int = 30,
    runner: Runner = subprocess.run,
    ocr_function: OcrFunction = run_ocr,
    pdftoppm: str | None = None,
    pdfinfo: str | None = None,
) -> dict[str, Any]:
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError(f"not a readable PDF: {source}")
    if max_pages < 1 or max_pages > 30:
        raise ValueError("max_pages must be between 1 and 30")
    if dpi < 72 or dpi > 300:
        raise ValueError("dpi must be between 72 and 300")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory must be empty: {output_dir}")
    render_command = pdftoppm or shutil.which("pdftoppm")
    info_command = pdfinfo or shutil.which("pdfinfo")
    if not render_command or not info_command:
        raise RuntimeError("Poppler pdftoppm and pdfinfo must both be available")
    source_hash_before = file_sha256(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        info = _run(runner, [info_command, str(source.resolve())], timeout)
    except subprocess.TimeoutExpired as exc:
        failure = _failure(None, "pdfinfo_timeout", exc)
        result = {
            "source_path": str(source.resolve()),
            "source_sha256": source_hash_before,
            "source_unchanged": source_hash_before == file_sha256(source),
            "page_count": None,
            "selected_pages": [],
            "selection_strategy": "not_started",
            "max_pages": max_pages,
            "completion_status": "failed",
            "semantic_review_status": "not_reviewed",
            "pages": [],
            "failure_ledger": [failure],
            "summary": {"selected": 0, "successful": 0, "failed": 0, "failure_count": 1},
            "recovery": {"automatic_retry": False, "resume_supported": False, "next_attempt_requires": "new_empty_output_directory"},
        }
        payload = {
            "contract_version": "data-lens-method-result/1.0",
            "method_id": METHOD_ID,
            "method_version": METHOD_VERSION,
            "status": "failed",
            "results": [result],
            "diagnostics": [{"failure_count": 1}, {"timed_out_stage": "pdfinfo"}],
            "boundaries": ["The timed-out command was not retried automatically; use a new empty output directory for an explicit retry."],
        }
        write_json(output_dir / "pdf-evidence.json", payload)
        return payload
    if info.returncode:
        raise RuntimeError(f"pdfinfo failed: {(info.stderr or info.stdout).strip()[:1000]}")
    page_count = parse_pdfinfo(info.stdout)
    selected_pages = parse_page_spec(page_spec, page_count, max_pages) if page_spec else page_indices(page_count, max_pages)
    pages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for page_number in selected_pages:
        prefix = output_dir / f"page-{page_number:04d}"
        rendered = prefix.with_suffix(".png")
        record: dict[str, Any] = {
            "page_number": page_number,
            "pdf_locator": {"source_sha256": source_hash_before, "page_number": page_number},
            "render_status": "pending",
            "ocr_status": "pending" if run_page_ocr else "not_requested",
            "semantic_review_status": "not_reviewed",
        }
        try:
            completed = _run(
                runner,
                [render_command, "-f", str(page_number), "-l", str(page_number), "-singlefile", "-png", "-r", str(dpi), str(source.resolve()), str(prefix.resolve())],
                timeout,
            )
        except subprocess.TimeoutExpired as exc:
            record["render_status"] = "failed"
            record["ocr_status"] = "blocked_by_render_failure" if run_page_ocr else "not_requested"
            failures.append(_failure(page_number, "render_timeout", exc))
            pages.append(record)
            continue
        if completed.returncode or not rendered.is_file():
            message = (completed.stderr or completed.stdout).strip() or "pdftoppm did not create the expected PNG"
            record["render_status"] = "failed"
            record["ocr_status"] = "blocked_by_render_failure" if run_page_ocr else "not_requested"
            failures.append(_failure(page_number, "render", message))
            pages.append(record)
            continue
        dimensions = image_size(rendered)
        record.update(
            {
                "render_status": "succeeded",
                "rendered_path": str(rendered.resolve()),
                "rendered_sha256": file_sha256(rendered),
                "rendered_dimensions": list(dimensions) if dimensions else None,
                "render_dpi": dpi,
            }
        )
        if run_page_ocr:
            try:
                ocr_payload = ocr_function(rendered, languages=languages, psms=psms, timeout=timeout)
                ocr_path = output_dir / f"page-{page_number:04d}.ocr.json"
                write_json(ocr_path, ocr_payload)
                record.update(
                    {
                        "ocr_status": "succeeded" if ocr_payload.get("status") == "succeeded" else "failed",
                        "ocr_output_path": str(ocr_path.resolve()),
                        "ocr_output_sha256": file_sha256(ocr_path),
                        "ocr_method_id": ocr_payload.get("method_id"),
                        "ocr_method_version": ocr_payload.get("method_version"),
                    }
                )
                if ocr_payload.get("status") != "succeeded":
                    failures.append(_failure(page_number, "ocr", "OCR completed without a usable text candidate"))
            except Exception as exc:
                record["ocr_status"] = "failed"
                failures.append(_failure(page_number, "ocr", exc))
        pages.append(record)
    source_unchanged = source_hash_before == file_sha256(source)
    if not source_unchanged:
        failures.append(_failure(None, "source_integrity", "source PDF hash changed during processing"))
    successful_pages = sum(1 for page in pages if page["render_status"] == "succeeded" and page["ocr_status"] in {"succeeded", "not_requested"})
    completion = "complete" if successful_pages == len(selected_pages) and not failures else "partial" if successful_pages else "failed"
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": source_hash_before,
        "source_unchanged": source_unchanged,
        "page_count": page_count,
        "selected_pages": selected_pages,
        "selection_strategy": "explicit_pages" if page_spec else "evenly_spaced_bounded_sample",
        "max_pages": max_pages,
        "completion_status": completion,
        "semantic_review_status": "not_reviewed",
        "pages": pages,
        "failure_ledger": failures,
        "summary": {"selected": len(selected_pages), "successful": successful_pages, "failed": len(selected_pages) - successful_pages, "failure_count": len(failures)},
        "recovery": None if not failures else {"automatic_retry": False, "resume_supported": False, "next_attempt_requires": "new_empty_output_directory"},
    }
    payload = {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "status": "succeeded" if completion == "complete" else "failed",
        "results": [result],
        "diagnostics": [{"pdfinfo_page_count": page_count}, {"failure_count": len(failures)}],
        "boundaries": [
            "Rendered pages and OCR text are locatable preparation artifacts, not semantic review or adopted findings.",
            "Failures are retained without automatic retry; successful pages do not imply full-document coverage when sampling was bounded.",
        ],
    }
    write_json(output_dir / "pdf-evidence.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Render bounded PDF pages, retain page/hash locators, run optional OCR, and write a failure ledger.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--pages", dest="page_spec", help="Explicit 1-based pages, for example 1,3-5")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--languages", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, action="append", dest="psms")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    payload = build_pdf_evidence(
        args.source,
        args.output_dir,
        max_pages=args.max_pages,
        page_spec=args.page_spec,
        dpi=args.dpi,
        run_page_ocr=not args.skip_ocr,
        languages=args.languages,
        psms=tuple(args.psms or DEFAULT_PSMS),
        timeout=args.timeout,
    )
    result = payload["results"][0]
    print(json.dumps({"output": str((args.output_dir / "pdf-evidence.json").resolve()), "status": payload["status"], **result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
