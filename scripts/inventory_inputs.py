from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _common import (
    SKILL_NAME,
    SKILL_VERSION,
    file_sha256,
    normalize_title,
    parse_publish_stamp,
    read_text_fallback,
    title_features,
    write_json,
)


ROLE_BY_EXTENSION = {
    ".md": "content_text",
    ".txt": "content_text",
    ".html": "content_text",
    ".htm": "content_text",
    ".mhtml": "content_text",
    ".pdf": "content_text",
    ".docx": "content_text",
    ".csv": "tabular_data",
    ".tsv": "tabular_data",
    ".xls": "tabular_data",
    ".xlsx": "tabular_data",
    ".png": "visual_layout",
    ".jpg": "visual_layout",
    ".jpeg": "visual_layout",
    ".webp": "visual_layout",
    ".gif": "visual_layout",
    ".mp3": "audio_video",
    ".wav": "audio_video",
    ".m4a": "audio_video",
    ".mp4": "audio_video",
    ".mov": "audio_video",
    ".mkv": "audio_video",
}

CANONICAL_PRIORITY = {".md": 0, ".txt": 1, ".html": 2, ".htm": 3, ".mhtml": 4}

TEXT_ARTICLE_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".mhtml"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
WORKBOOK_EXTENSIONS = {".xls", ".xlsx"}
TABLE_EXTENSIONS = {".csv", ".tsv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
AUDIO_VIDEO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv"}


def infer_evidence_role(path: Path) -> str:
    suffix = path.suffix.lower()
    default = ROLE_BY_EXTENSION.get(suffix, "unclassified")
    if suffix in {".csv", ".tsv", ".xls", ".xlsx"} and re.search(r"评论|留言|评价|comment|review|voc", path.stem, re.I):
        return "audience_voice"
    if suffix in {".csv", ".tsv", ".xls", ".xlsx"} and re.search(
        r"tendency|article[_ -]?analysis|user[_ -]?analysis|阅读|点赞|转发|收藏|公众号后台|metrics?|performance",
        path.stem,
        re.I,
    ):
        return "performance_table"
    return default


def markdown_profile(path: Path) -> dict[str, Any]:
    text, encoding = read_text_fallback(path)
    heading = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    stem_date, stem_title = parse_publish_stamp(path.stem)
    title = heading.group(1).strip() if heading else stem_title
    body_without_images = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)
    visible = re.sub(r"[#*_>`~\[\]()\-]+", "", body_without_images)
    return {
        "encoding": encoding,
        "title": title,
        "title_norm": normalize_title(title),
        "publish_date": stem_date,
        "body_chars_approx": len(re.sub(r"\s+", "", visible)),
        "paragraphs_approx": len([line for line in body_without_images.splitlines() if line.strip()]),
        "image_refs": len(re.findall(r"!\[[^\]]*\]\([^\)]*\)", text)),
        "headings": len(re.findall(r"^#{1,6}\s+", text, re.M)),
        "bold_pairs": len(re.findall(r"\*\*.+?\*\*", text, re.S)),
        **title_features(title),
    }


def group_key(path: Path) -> str:
    if path.suffix.lower() in CANONICAL_PRIORITY:
        return str(path.parent.resolve()).lower() + "|" + normalize_title(path.stem)
    return str(path.resolve()).lower()


def source_family_stem(stem: str) -> str:
    """Remove only common copy/version suffixes; never use this as automatic deduplication."""
    value = stem.strip()
    patterns = (
        r"\s*[\(（]\d+[\)）]\s*$",
        r"\s*[-_ ]?(?:copy|副本)\s*\d*\s*$",
        r"\s*[-_ ]?(?:final|最终版?|修订版?|最新版)\s*$",
        r"\s*[-_ ]?v\d+(?:\.\d+)*\s*$",
    )
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            revised = re.sub(pattern, "", value, flags=re.I).strip()
            if revised and revised != value:
                value = revised
                changed = True
    return normalize_title(value) or normalize_title(stem)


def collection_date_hint(path: Path) -> str | None:
    """Infer a collection date from dated folders or filenames without claiming a business date."""
    candidates = list(path.parts[-4:-1]) + [path.stem]
    for value in reversed(candidates):
        text = str(value).strip()
        match = re.search(r"(?<!\d)(20\d{2})[-_.年/]?(\d{1,2})[-_.月/]?(\d{1,2})(?:日)?(?!\d)", text)
        if match:
            year, month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
        match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日(?!\d)", text)
        if match:
            month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"--{month:02d}-{day:02d}"
        match = re.fullmatch(r"(\d{2})(\d{2})", text)
        if match:
            month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"--{month:02d}-{day:02d}"
        match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", text)
        if match:
            year, month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def repeated_export_family_stem(stem: str) -> str:
    """Build a conservative repeated-export hint; it is routing metadata, never automatic deduplication."""
    value = stem
    value = re.sub(r"(?<!\d)20\d{2}[-_.年/]?\d{1,2}[-_.月/]?\d{1,2}(?:日)?(?!\d)", " ", value)
    value = re.sub(r"(?<!\d)\d{1,2}月\d{1,2}日(?!\d)", " ", value)
    value = re.sub(r"(?<!\d)20\d{6}(?!\d)", " ", value)
    value = re.sub(r"(?<!\d)\d{10,}(?!\d)", " ", value)
    value = re.sub(r"(?:^|[-_ ])(?:export|download|data)[-_ ]*\d+(?=$|[-_ ])", " ", value, flags=re.I)
    value = re.sub(r"[\s_\-\.]+", " ", value).strip()
    return normalize_title(value) or "unnamed_export"


def sequence_family_stem(stem: str) -> str:
    """Return a conservative family hint for screenshots/pages; this is review-only."""
    value = re.sub(
        r"(?:[-_ ]?(?:page|p|截图|第)[-_ ]*\d+\s*(?:页)?)$|(?:[\(（]\d+[\)）])$",
        "",
        stem.strip(),
        flags=re.I,
    ).strip()
    return normalize_title(value) if value and value != stem.strip() else ""


def capture_session_key(path: Path) -> str | None:
    match = re.search(r"(?:screenshot|screen[_ -]?shot|截图)[_ -]?(\d{4}[-_]\d{2}[-_]\d{2})[_ -]?(\d{2})\d{4}", path.stem, re.I)
    if not match:
        return None
    capture_date = match.group(1).replace("_", "-")
    return str(path.parent.resolve()).lower() + f"|{capture_date}|{match.group(2)}"


def container_type(path: Path, publish_date: str | None) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_ARTICLE_EXTENSIONS:
        return "article_candidate" if publish_date else "text_document"
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in WORKBOOK_EXTENSIONS:
        return "workbook"
    if suffix in TABLE_EXTENSIONS:
        return "table"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_VIDEO_EXTENSIONS:
        return "recording"
    return "file"


def stable_container_id(path: Path) -> str:
    return "SRC-" + hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:12]


def collect(paths: list[Path], hash_max_mb: int) -> dict[str, Any]:
    files: list[Path] = []
    for supplied in paths:
        if supplied.is_file():
            files.append(supplied.resolve())
        elif supplied.is_dir():
            files.extend(item.resolve() for item in supplied.rglob("*") if item.is_file())
        else:
            raise FileNotFoundError(str(supplied))

    records: list[dict[str, Any]] = []
    grouped: dict[str, list[int]] = defaultdict(list)
    for path in sorted(set(files), key=lambda value: str(value).lower()):
        stat = path.stat()
        suffix = path.suffix.lower()
        record: dict[str, Any] = {
            "source_container_id": stable_container_id(path),
            "path": str(path),
            "name": path.name,
            "extension": suffix,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "evidence_role": infer_evidence_role(path),
            "group_key": group_key(path),
            "canonical": True,
            "variant_of": None,
            "sha256": file_sha256(path) if stat.st_size <= hash_max_mb * 1024 * 1024 else None,
            "exact_duplicate_of": None,
            "source_family_key": str(path.parent.resolve()).lower() + "|" + source_family_stem(path.stem),
            "possible_sequence_key": None,
            "capture_session_key": None,
            "collection_date_hint": collection_date_hint(path),
            "repeated_export_family_key": (
                repeated_export_family_stem(path.stem)
                if suffix in WORKBOOK_EXTENSIONS.union(TABLE_EXTENSIONS)
                else None
            ),
        }
        if suffix == ".md":
            record.update(markdown_profile(path))
        else:
            publish_date, title = parse_publish_stamp(path.stem)
            record.update(
                {
                    "title": title,
                    "title_norm": normalize_title(title),
                    "publish_date": publish_date,
                }
            )
        record["container_type"] = container_type(path, record.get("publish_date"))
        record["analysis_unit_status"] = "source_container_only"
        sequence_key = sequence_family_stem(path.stem) if suffix in IMAGE_EXTENSIONS else ""
        if sequence_key:
            record["possible_sequence_key"] = str(path.parent.resolve()).lower() + "|" + sequence_key
        if suffix in IMAGE_EXTENSIONS:
            record["capture_session_key"] = capture_session_key(path)
        grouped[record["group_key"]].append(len(records))
        records.append(record)

    canonical_count = 0
    for indices in grouped.values():
        if len(indices) == 1:
            canonical_count += 1
            continue
        ranked = sorted(
            indices,
            key=lambda idx: (CANONICAL_PRIORITY.get(records[idx]["extension"], 99), records[idx]["name"].lower()),
        )
        canonical_index = ranked[0]
        canonical_count += 1
        for idx in ranked[1:]:
            records[idx]["canonical"] = False
            records[idx]["variant_of"] = records[canonical_index]["path"]

    # Exact copies across different names are one canonical source container.
    hash_groups: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        if record.get("sha256"):
            hash_groups[str(record["sha256"])].append(index)
    for indices in hash_groups.values():
        canonical_indices = [index for index in indices if records[index]["canonical"]]
        if len(canonical_indices) < 2:
            continue
        keeper = sorted(canonical_indices, key=lambda index: records[index]["name"].lower())[0]
        for index in canonical_indices:
            if index == keeper:
                continue
            records[index]["canonical"] = False
            records[index]["exact_duplicate_of"] = records[keeper]["path"]

    family_groups: dict[str, list[int]] = defaultdict(list)
    sequence_groups: dict[str, list[int]] = defaultdict(list)
    capture_groups: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        family_groups[str(record["source_family_key"])].append(index)
        if record.get("possible_sequence_key"):
            sequence_groups[str(record["possible_sequence_key"])].append(index)
        if record.get("capture_session_key"):
            capture_groups[str(record["capture_session_key"])].append(index)
    for indices in family_groups.values():
        relation = "possible_version" if len(indices) > 1 else "single"
        for index in indices:
            records[index]["source_family_relation"] = relation
    for indices in sequence_groups.values():
        if len(indices) > 1:
            for index in indices:
                records[index]["sequence_relation"] = "possible_continuation"
                records[index]["requires_sequence_review"] = True
    for record in records:
        record.setdefault("sequence_relation", "single")
        record.setdefault("requires_sequence_review", False)
    for indices in capture_groups.values():
        if len(indices) > 1:
            for index in indices:
                records[index]["capture_session_relation"] = "same_capture_session_candidate"
                records[index]["requires_sequence_review"] = True
    for record in records:
        record.setdefault("capture_session_relation", "single")

    canonical_count = sum(1 for record in records if record["canonical"])
    roles = Counter(record["evidence_role"] for record in records if record["canonical"])
    extensions = Counter(record["extension"] or "[no extension]" for record in records)
    container_types = Counter(record["container_type"] for record in records if record["canonical"])
    canonical_tables = [
        record for record in records
        if record["canonical"] and record["extension"] in WORKBOOK_EXTENSIONS.union(TABLE_EXTENSIONS)
    ]
    date_partitions = {str(record["collection_date_hint"]) for record in canonical_tables if record.get("collection_date_hint")}
    repeated_table_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in canonical_tables:
        repeated_table_groups[str(record.get("repeated_export_family_key") or "unnamed_export")].append(record)
    repeated_table_families = {
        key: len(items) for key, items in repeated_table_groups.items()
        if len(items) >= 2
    }
    return {
        "inventory_version": "1.2",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "supplied_paths": [str(path.resolve()) for path in paths],
        "summary": {
            "physical_files": len(records),
            "canonical_items": canonical_count,
            "sibling_variants": len(records) - canonical_count,
            "by_evidence_role": dict(sorted(roles.items())),
            "by_extension": dict(sorted(extensions.items())),
            "by_container_type": dict(sorted(container_types.items())),
            "exact_duplicate_files": sum(1 for record in records if record.get("exact_duplicate_of")),
            "possible_version_families": sum(1 for indices in family_groups.values() if len(indices) > 1),
            "possible_sequence_families": sum(1 for indices in sequence_groups.values() if len(indices) > 1),
            "capture_session_families": sum(1 for indices in capture_groups.values() if len(indices) > 1),
            "table_files": len(canonical_tables),
            "date_partition_count": len(date_partitions),
            "date_partitioned_table_files": sum(1 for record in canonical_tables if record.get("collection_date_hint")),
            "repeated_table_family_count": len(repeated_table_families),
            "repeated_table_families": dict(sorted(repeated_table_families.items())),
            "unitization_required": canonical_count,
        },
        "unit_boundary": "清单记录的是来源容器，不自动把一个PDF、DOCX、工作簿或截图文件等同于最终分析单元；项目、岗位、方法主张、课程章节等单元必须在选路后再识别。",
        "files": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory mixed corpus inputs and deduplicate sibling formats.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hash-max-mb", type=int, default=64)
    args = parser.parse_args()
    payload = collect(args.paths, args.hash_max_mb)
    write_json(args.output, payload)
    print(f"inventory={args.output} physical={payload['summary']['physical_files']} canonical={payload['summary']['canonical_items']}")


if __name__ == "__main__":
    main()
