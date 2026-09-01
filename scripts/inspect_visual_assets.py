from __future__ import annotations

import argparse
import html as html_lib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from _common import file_sha256, read_text_fallback, write_json
from extract_wechat_article_body import BODY_END_MARKER, BODY_START_MARKER, extract_wechat_article
from multimodal_inventory import image_size


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DOCUMENT_EXTENSIONS = {".md", ".html", ".htm", ".mhtml"}


def normalize_reference(value: Any) -> str:
    return html_lib.unescape(re.sub(r"\s+", "", str(value or ""))).strip()


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for supplied in paths:
        if supplied.is_file():
            files.append(supplied.resolve())
        elif supplied.is_dir():
            files.extend(path.resolve() for path in supplied.rglob("*") if path.is_file())
        else:
            raise FileNotFoundError(supplied)
    return sorted(set(files), key=lambda path: str(path).lower())


def image_profile(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "sha256": file_sha256(path), "size_bytes": path.stat().st_size}
    error_name = "UnknownError"
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        error_name = type(exc).__name__
        try:
            dimensions = image_size(path)
        except Exception:
            dimensions = None
        if dimensions:
            width, height = dimensions
            record.update(
                {
                    "pixel_status": "readable",
                    "ocr_status": "not_run",
                    "semantic_review_status": "not_reviewed",
                    "source_mapping_status": "unmapped",
                    "width": width,
                    "height": height,
                    "aspect_ratio": round(width / height, 4) if height else None,
                    "orientation": "square" if width == height else "landscape" if width > height else "portrait",
                    "mode": None,
                    "format": path.suffix.lstrip(".").upper(),
                    "frames": None,
                    "metadata_reader": "stdlib_header",
                    "capability_note": "Pillow is unavailable; dimensions were read using the bounded standard-library parser.",
                }
            )
            return record
    else:
        try:
            with Image.open(path) as image:
                width, height = image.size
                record.update(
                    {
                        "pixel_status": "readable",
                        "ocr_status": "not_run",
                        "semantic_review_status": "not_reviewed",
                        "source_mapping_status": "unmapped",
                        "width": width,
                        "height": height,
                        "aspect_ratio": round(width / height, 4) if height else None,
                        "orientation": "square" if width == height else "landscape" if width > height else "portrait",
                        "mode": image.mode,
                        "format": image.format,
                        "frames": int(getattr(image, "n_frames", 1)),
                        "metadata_reader": "pillow",
                    }
                )
                return record
        except Exception as exc:
            error_name = type(exc).__name__
    # deterministic record of unreadable/corrupt/unsupported assets
    record.update(
        {
            "pixel_status": "unreadable",
            "ocr_status": "not_run",
            "semantic_review_status": "not_reviewed",
            "source_mapping_status": "unmapped",
            "error": error_name,
        }
    )
    return record


def raw_references(path: Path, text: str) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".md":
        return [
            {"reference": normalize_reference(match.group(1)), "origin_line": text.count("\n", 0, match.start()) + 1}
            for match in re.finditer(r"!\[[^\]]*\]\((.*?)\)", text, flags=re.S)
        ]
    records = []
    for match in re.finditer(r"<img\b[^>]*>", text, flags=re.I):
        tag = match.group(0)
        attributes = {
            key.lower(): value
            for key, _, value in re.findall(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", tag, flags=re.S)
        }
        reference = attributes.get("data-src") or attributes.get("data-original") or attributes.get("src")
        if reference:
            records.append({"reference": normalize_reference(reference), "origin_line": text.count("\n", 0, match.start()) + 1})
    return records


def extract_reference_records(path: Path, document_scope: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    text, _ = read_text_fallback(path)
    all_records = raw_references(path, text)
    detected_wechat = (
        path.suffix.lower() == ".md" and BODY_START_MARKER in text and BODY_END_MARKER in text
    ) or (
        path.suffix.lower() in {".html", ".htm", ".mhtml"} and re.search(r"\bid=[\"']js_content[\"']", text, re.I) is not None
    )
    use_wechat = document_scope == "wechat-body" or (document_scope == "auto" and detected_wechat)
    if not use_wechat:
        return [{**item, "source_region": "whole_document", "analysis_eligibility": "eligible"} for item in all_records], None
    boundary = extract_wechat_article(path, allow_fallback=document_scope == "wechat-body")
    body = str(boundary.pop("body_text", ""))
    if boundary.get("requires_manual_confirmation") or not body:
        return [
            {**item, "source_region": "boundary_unconfirmed", "analysis_eligibility": "manual_required", "exclusion_reason": "微信公众号正文边界未确认"}
            for item in all_records
        ], boundary
    if path.suffix.lower() == ".md" and boundary.get("origin_start_line") and boundary.get("origin_end_line"):
        start_line = int(boundary["origin_start_line"])
        end_line = int(boundary["origin_end_line"])
        return [
            {
                **item,
                "source_region": "author_body" if start_line <= int(item.get("origin_line") or 0) <= end_line else "page_chrome_comment_or_footer",
                "analysis_eligibility": "eligible" if start_line <= int(item.get("origin_line") or 0) <= end_line else "excluded",
                **({} if start_line <= int(item.get("origin_line") or 0) <= end_line else {"exclusion_reason": "位于已确认作者正文范围之外"}),
            }
            for item in all_records
        ], boundary
    body_records = raw_references(path, body) if path.suffix.lower() == ".md" else [
        {"reference": normalize_reference(item.get("remote_reference")), "origin_line": None}
        for item in boundary.get("images", [])
        if item.get("remote_reference")
    ]
    remaining = Counter(str(item.get("reference") or "") for item in body_records)
    classified = []
    for item in all_records:
        reference = str(item.get("reference") or "")
        if remaining[reference] > 0:
            remaining[reference] -= 1
            classified.append({**item, "source_region": "author_body", "analysis_eligibility": "eligible"})
        else:
            classified.append({**item, "source_region": "page_chrome_comment_or_footer", "analysis_eligibility": "excluded", "exclusion_reason": "位于已确认作者正文范围之外"})
    return classified, boundary


def inspect(paths: list[Path], document_scope: str = "auto") -> dict[str, Any]:
    if document_scope not in {"auto", "whole", "wechat-body"}:
        raise ValueError(f"unsupported document scope: {document_scope}")
    files = iter_files(paths)
    images = [image_profile(path) for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]
    sha_groups: dict[str, list[str]] = defaultdict(list)
    for item in images:
        sha_groups[item["sha256"]].append(item["path"])
    documents = []
    reference_counts: Counter[str] = Counter()
    excluded_reference_counts: Counter[str] = Counter()
    canonical_eligible_references: set[tuple[str, int, str]] = set()
    for path in files:
        if path.suffix.lower() not in DOCUMENT_EXTENSIONS:
            continue
        refs, boundary = extract_reference_records(path, document_scope)
        resolved = []
        eligible_index = 0
        for record in refs:
            ref = str(record.get("reference") or "")
            cleaned = ref.strip().split()[0].strip("<>\"")
            parsed = urlparse(cleaned)
            if parsed.scheme in {"http", "https"}:
                state = "remote_uninspected"
                target = cleaned
            elif cleaned.startswith("data:"):
                state = "embedded_uninspected"
                target = "data-uri"
            else:
                candidate = (path.parent / cleaned).resolve()
                state = "local_resolved" if candidate.is_file() else "local_missing"
                target = str(candidate)
            if record.get("analysis_eligibility") == "eligible":
                eligible_index += 1
                reference_counts[state] += 1
                canonical_eligible_references.add((str(path.with_suffix("")).lower(), eligible_index, cleaned))
            else:
                excluded_reference_counts[str(record.get("analysis_eligibility") or "unknown")] += 1
            resolved.append({**record, "reference": cleaned, "state": state, "target": target})
        documents.append({
            "path": str(path),
            "reference_count": sum(1 for item in refs if item.get("analysis_eligibility") == "eligible"),
            "all_reference_count": len(refs),
            "excluded_reference_count": sum(1 for item in refs if item.get("analysis_eligibility") == "excluded"),
            "manual_reference_count": sum(1 for item in refs if item.get("analysis_eligibility") == "manual_required"),
            "body_boundary": boundary,
            "references": resolved,
        })
    orientation = Counter(item.get("orientation", "unknown") for item in images)
    return {
        "visual_inventory_version": "1.2",
        "document_scope": document_scope,
        "summary": {
            "local_image_files": len(images),
            "pixel_readable_images": sum(1 for item in images if item.get("pixel_status") == "readable"),
            "semantic_reviewed_images": sum(1 for item in images if item.get("semantic_review_status") == "reviewed"),
            "ocr_complete_images": sum(1 for item in images if item.get("ocr_status") == "complete"),
            "source_mapped_images": sum(1 for item in images if item.get("source_mapping_status") == "mapped"),
            "unreadable_images": sum(1 for item in images if item.get("pixel_status") != "readable"),
            "documents_scanned": len(documents),
            "references": dict(sorted(reference_counts.items())),
            "eligible_references_by_container": sum(reference_counts.values()),
            "canonical_eligible_references": len(canonical_eligible_references),
            "excluded_or_manual_references": dict(sorted(excluded_reference_counts.items())),
            "orientation": dict(sorted(orientation.items())),
            "duplicate_image_groups": sum(1 for group in sha_groups.values() if len(group) > 1),
        },
        "coverage_boundary": "pixel_status=readable 只证明文件和像素可读取，不等于完成OCR、语义观察或来源映射；微信公众号文档在正文边界确认后只把作者正文内引用计入可分析引用，页控件、评论和页尾引用保留但排除。只有 semantic_review_status=reviewed 且带可定位证据的图片才能支持视觉结论。",
        "images": images,
        "documents": documents,
        "duplicate_groups": [paths for paths in sha_groups.values() if len(paths) > 1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory local visual evidence and distinguish inspected images from uninspected references.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-scope", choices=("auto", "whole", "wechat-body"), default="auto")
    args = parser.parse_args()
    result = inspect(args.paths, args.document_scope)
    write_json(args.output, result)
    print(
        f"visuals={args.output} pixel_readable={result['summary']['pixel_readable_images']} "
        f"semantic_reviewed={result['summary']['semantic_reviewed_images']} "
        f"remote_uninspected={result['summary']['references'].get('remote_uninspected', 0)}"
    )


if __name__ == "__main__":
    main()
