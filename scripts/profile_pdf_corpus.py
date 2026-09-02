from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import unicodedata
from pathlib import Path
from typing import Any

from _common import file_sha256, write_json


METHOD_ID = "data_lens.pdf_structure_profile"
METHOD_VERSION = "0.1.0"
COMMON_CHINESE = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面"
    "而方后多定行学法所民得经之进着等部度家里如自理起小现实都两体当使点从业本去把性好应开合还因由其些然前"
    "外天事相全表间样与关各重新内数正心反你明看原利比或但第向道此变条只没结解问意月很情者最立代想已通并提"
    "直题程展果料象员入常文总次品式活设及管特件长求基资边流路级少接知较将组见计别手角期根论运指区放决被做"
    "必先回则任取据处理世怎际"
)


def _text_state(text: str) -> tuple[str, dict[str, Any]]:
    normalized = unicodedata.normalize("NFKC", text or "")
    visible = [char for char in normalized if not char.isspace()]
    count = len(visible)
    if count < 20:
        return "empty_or_negligible", {"extracted_char_count": count, "language_char_ratio": 0.0, "private_use_ratio": 0.0}
    language_chars = sum(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in visible)
    private_use = sum(unicodedata.category(char) == "Co" or char == "\ufffd" for char in visible)
    cjk = [char for char in visible if "CJK UNIFIED IDEOGRAPH" in unicodedata.name(char, "")]
    common_cjk_ratio = sum(char in COMMON_CHINESE for char in cjk) / len(cjk) if cjk else 0.0
    language_ratio = language_chars / count
    private_ratio = private_use / count
    suspicious_cjk = len(cjk) >= 20 and common_cjk_ratio < 0.12
    state = "garbled_candidate" if language_ratio < 0.45 or private_ratio > 0.02 or suspicious_cjk else "usable_candidate"
    return state, {
        "extracted_char_count": count,
        "language_char_ratio": round(language_ratio, 4),
        "private_use_ratio": round(private_ratio, 4),
        "common_cjk_ratio": round(common_cjk_ratio, 4),
        "extracted_text_sha256": hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest(),
    }


def _xobject_count(page: Any) -> int:
    try:
        resources = page.get("/Resources") or {}
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        xobjects = resources.get("/XObject") or {}
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        return len(xobjects)
    except Exception:
        return 0


def bounded_page_plan(page_count: int, maximum: int = 12, priority_pages: list[int] | None = None) -> list[int]:
    if page_count < 1:
        return []
    if maximum < 1:
        raise ValueError("maximum must be positive")
    if maximum == 1:
        return [1]
    if maximum <= 3:
        return sorted({round(index * (page_count - 1) / (maximum - 1)) + 1 for index in range(maximum)})
    selected = set(range(1, min(page_count, 3) + 1))
    selected.add(page_count)
    priorities = sorted({page for page in (priority_pages or []) if 1 <= page <= page_count and page not in selected})
    priority_limit = min(len(priorities), max(0, maximum // 3))
    for _ in range(priority_limit):
        chosen = max(priorities, key=lambda page: (min(abs(page - current) for current in selected), -page))
        selected.add(chosen)
        priorities.remove(chosen)
    targets = sorted({round(index * (page_count - 1) / max(1, maximum - 1)) + 1 for index in range(maximum)})
    while len(selected) < min(maximum, page_count):
        remaining = [page for page in targets if page not in selected]
        if not remaining:
            remaining = [page for page in range(1, page_count + 1) if page not in selected]
        chosen = max(remaining, key=lambda page: (min(abs(page - current) for current in selected), -page))
        selected.add(chosen)
    return sorted(selected)


def _outline_count(reader: Any) -> int:
    try:
        outline = reader.outline
    except Exception:
        return 0

    def count(items: list[Any]) -> int:
        return sum(count(item) if isinstance(item, list) else 1 for item in items)

    return count(outline) if isinstance(outline, list) else 0


def profile_pdf(source: Path, *, max_ocr_pages: int = 12) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("profile-pdf requires the optional pypdf package") from exc
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError(f"not a readable PDF: {source}")
    reader = PdfReader(str(source), strict=False)
    pages: list[dict[str, Any]] = []
    heights: list[float] = []
    for index, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        heights.append(height)
        try:
            text = page.extract_text() or ""
            extraction_error = None
        except Exception as exc:
            text = ""
            extraction_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        state, text_metrics = _text_state(text)
        pages.append(
            {
                "page_number": index,
                "width_points": round(width, 2),
                "height_points": round(height, 2),
                "aspect_ratio_height_to_width": round(height / width, 3) if width else None,
                "top_level_xobject_count": _xobject_count(page),
                "text_layer_state": state,
                "text_metrics": text_metrics,
                "extraction_error": extraction_error,
            }
        )
    median_height = statistics.median(heights) if heights else 0.0
    long_pages: list[int] = []
    dimension_change_pages: list[int] = []
    previous_shape: tuple[int, int] | None = None
    for page in pages:
        width = float(page["width_points"])
        height = float(page["height_points"])
        shape = (round(width), round(height))
        if height >= 2000 or (width and height / width >= 4.0) or (median_height and height >= median_height * 2.5):
            long_pages.append(int(page["page_number"]))
        if previous_shape is not None and (abs(shape[0] - previous_shape[0]) > 5 or abs(shape[1] - previous_shape[1]) > 5):
            dimension_change_pages.append(int(page["page_number"]))
        previous_shape = shape
    state_counts: dict[str, int] = {}
    for page in pages:
        state = str(page["text_layer_state"])
        state_counts[state] = state_counts.get(state, 0) + 1
    page_count = len(pages)
    long_share = len(long_pages) / page_count if page_count else 0.0
    if page_count and long_share >= 0.5:
        unitization = {
            "status": "provisional_page_units",
            "provisional_unit_count": page_count,
            "unit_hint": "Each unusually tall PDF page is a provisional internal case/project unit until OCR or visual review confirms boundaries.",
        }
    elif page_count > 1:
        unitization = {
            "status": "internal_units_unresolved",
            "provisional_unit_count": None,
            "unit_hint": "PDF files and pages must not be treated as final analysis units; use bounded OCR/visual review to locate chapters, projects, or cases.",
        }
    else:
        unitization = {"status": "single_page_source", "provisional_unit_count": 1, "unit_hint": "The single page is the provisional unit."}
    priority = sorted(set(long_pages + dimension_change_pages))
    recommended_cap = min(max_ocr_pages, 6) if long_share >= 0.5 else max_ocr_pages
    recommended_pages = bounded_page_plan(page_count, recommended_cap, priority)
    return {
        "source_path": str(source.resolve()),
        "source_sha256": file_sha256(source),
        "file_size_bytes": source.stat().st_size,
        "page_count": page_count,
        "outline_entry_count": _outline_count(reader),
        "text_layer_summary": dict(sorted(state_counts.items())),
        "page_geometry_summary": {
            "median_height_points": round(median_height, 2),
            "long_page_count": len(long_pages),
            "long_page_share": round(long_share, 4),
            "long_pages": long_pages,
            "dimension_change_pages": dimension_change_pages,
        },
        "unitization": unitization,
        "recommended_ocr_pages": recommended_pages,
        "recommended_render_dpi": 72 if long_share >= 0.5 else 120,
        "recommended_ocr_page_cap": recommended_cap,
        "selection_strategy": "front_matter_plus_geometry_changes_plus_evenly_spaced_bounded",
        "pages": pages,
        "boundaries": [
            "Text-layer state is a deterministic screening signal, not semantic validation.",
            "Provisional page units require OCR or visual confirmation before they become adopted project/chapter units.",
            "Recommended OCR pages are a bounded structural pilot and do not imply full-document coverage.",
        ],
    }


def build_profile(sources: list[Path], *, max_ocr_pages: int = 12) -> dict[str, Any]:
    profiles = [profile_pdf(source, max_ocr_pages=max_ocr_pages) for source in sources]
    return {
        "contract_version": "data-lens-pdf-structure-profile/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "source_count": len(profiles),
        "physical_file_count": len(profiles),
        "physical_page_count": sum(item["page_count"] for item in profiles),
        "analysis_unit_status": "requires_internal_unit_confirmation" if any(item["unitization"]["status"] == "internal_units_unresolved" for item in profiles) else "provisional_units_available",
        "sources": profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile PDF structure and propose bounded, non-sequential OCR pages without claiming semantic units.")
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-ocr-pages", type=int, default=12)
    args = parser.parse_args()
    if not 3 <= args.max_ocr_pages <= 30:
        raise ValueError("max-ocr-pages must be between 3 and 30")
    payload = build_profile(args.sources, max_ocr_pages=args.max_ocr_pages)
    write_json(args.output, payload)
    print(json.dumps({"output": str(args.output.resolve()), "sources": payload["source_count"], "pages": payload["physical_page_count"], "analysis_unit_status": payload["analysis_unit_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
