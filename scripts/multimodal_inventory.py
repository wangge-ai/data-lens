from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

from _common import file_sha256, write_json


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
PDF_EXTENSIONS = {".pdf"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _jpeg_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index:index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and index + 7 < len(data):
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            return width, height
        if length < 2:
            break
        index += length
    return None


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except (ImportError, OSError):
        pass
    header = path.read_bytes()[:32]
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return _jpeg_size(path)
    return None


def _ffprobe(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable:
        return {}
    completed = subprocess.run(
        [executable, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if completed.returncode:
        return {"ffprobe_error": completed.stderr.strip()[:500]}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ffprobe_error": "invalid JSON output"}
    result: dict[str, Any] = {}
    duration = payload.get("format", {}).get("duration")
    if duration is not None:
        try:
            result["duration_ms"] = round(float(duration) * 1000)
        except (TypeError, ValueError):
            pass
    result["streams"] = payload.get("streams", [])
    return result


def _pdf_pages(path: Path) -> int | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    count = len(re.findall(rb"/Type\s*/Page\b", raw))
    return count or None


def collect(source: Path) -> dict[str, Any]:
    root = source if source.is_dir() else source.parent
    paths = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
    items: list[dict[str, Any]] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            medium = "image"
        elif suffix in PDF_EXTENSIONS:
            medium = "pdf"
        elif suffix in AUDIO_EXTENSIONS:
            medium = "audio"
        elif suffix in VIDEO_EXTENSIONS:
            medium = "video"
        else:
            continue
        relative = path.relative_to(root).as_posix()
        item: dict[str, Any] = {
            "source_path": relative,
            "source_sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
            "medium": medium,
            "processing_state": "metadata_only",
            "semantic_review": "required",
            "allowed_claims": ["file exists and metadata shown here was observed"],
            "cannot_prove": ["content, meaning, layout role, speaker claim, event sequence, or causal interpretation"],
        }
        if medium == "image":
            size = image_size(path)
            if size:
                item["width"], item["height"] = size
            item["required_locator"] = "pixel_region_or_explicit_full_frame"
        elif medium == "pdf":
            item["page_count_candidate"] = _pdf_pages(path)
            item["required_locator"] = "page_number_and_optional_region"
        else:
            item.update(_ffprobe(path))
            item["required_locator"] = "start_ms_and_end_ms_or_frame_timestamp"
        items.append(item)
    return {
        "contract_version": "data-lens-multimodal-inventory/1.0",
        "source_container_count": len(items),
        "items": items,
        "boundary": "Metadata inventory is not OCR, transcription, frame review, or semantic analysis.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory multimodal sources and their evidence requirements.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = collect(args.source)
    write_json(args.output, payload)
    print(f"multimodal_inventory={args.output} items={len(payload['items'])}")


if __name__ == "__main__":
    main()
