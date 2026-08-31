from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json, read_text_fallback, write_json
from extract_wechat_article_body import extract_wechat_article, html_js_content


TIMESTAMP_RE = re.compile(r"^\[(\d{12})\](.+)$")
IMAGE_NUMBER_RE = re.compile(r"_(\d+)$")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^\)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>", flags=re.I)


def compact_title(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).lower()


def split_archive_stem(path: Path) -> tuple[str, str]:
    match = TIMESTAMP_RE.match(path.stem)
    if not match:
        raise ValueError(f"archive_name_missing_timestamp:{path}")
    return match.group(1), match.group(2)


def body_remote_references(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    boundary = extract_wechat_article(path, allow_fallback=True)
    body = str(boundary.pop("body_text", ""))
    records: list[dict[str, Any]] = []
    for match in re.finditer(r"!\[[^\]]*\]\((.*?)\)", body, flags=re.S):
        reference = re.sub(r"\s+", "", match.group(1)).strip()
        line_number = body.count("\n", 0, match.start()) + 1
        records.append({"body_index": len(records) + 1, "line": line_number, "remote_reference": reference})
    return records, boundary


def find_article_asset_dir(images_root: Path, archive_title: str) -> tuple[Path | None, str]:
    target = compact_title(archive_title)
    candidates: list[tuple[int, Path, str]] = []
    for directory in images_root.iterdir() if images_root.is_dir() else []:
        if not directory.is_dir():
            continue
        candidate = compact_title(directory.name)
        if target == candidate:
            candidates.append((3, directory, "exact_title"))
        elif candidate.startswith(target) or target.startswith(candidate):
            candidates.append((2, directory, "prefix_title"))
    if not candidates:
        return None, "unmatched"
    candidates.sort(key=lambda item: (item[0], min(len(target), len(compact_title(item[1].name)))), reverse=True)
    best = candidates[0]
    if len(candidates) > 1 and candidates[1][0:1] == best[0:1] and compact_title(candidates[1][1].name) == compact_title(best[1].name):
        return None, "ambiguous"
    return best[1], best[2]


def numbered_images(asset_dir: Path) -> dict[int, Path]:
    records: dict[int, Path] = {}
    for path in asset_dir.iterdir():
        if not path.is_file():
            continue
        match = IMAGE_NUMBER_RE.search(path.stem)
        if match:
            records[int(match.group(1))] = path.resolve()
    return records


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None, None


def html_body_profiles(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text, _ = read_text_fallback(path)
    parsed = html_js_content(text)
    if parsed.get("status") == "confirmed_js_content":
        return list(parsed.get("images") or [])
    return []


def locate_cover(cover_root: Path, timestamp: str, archive_title: str) -> Path | None:
    target = compact_title(archive_title)
    matches = []
    for path in cover_root.iterdir() if cover_root.is_dir() else []:
        if not path.is_file() or not path.name.startswith(f"[{timestamp}]_"):
            continue
        candidate_title = path.stem.split("]_", 1)[-1]
        candidate = compact_title(candidate_title)
        if candidate == target or candidate.startswith(target) or target.startswith(candidate):
            matches.append(path.resolve())
    return matches[0] if len(matches) == 1 else None


def map_article(path: Path, fixed_tail_hashes: set[str] | None = None) -> dict[str, Any]:
    timestamp, archive_title = split_archive_stem(path)
    source_root = path.parent
    refs, body_boundary = body_remote_references(path)
    asset_dir, match_type = find_article_asset_dir(source_root / "图片", archive_title)
    cover = locate_cover(source_root / "封面", timestamp, archive_title)
    html_path = path.with_suffix(".html")
    html_profiles = html_body_profiles(html_path)
    local_by_number = numbered_images(asset_dir) if asset_dir else {}
    ordered_local = sorted(local_by_number.items())
    fixed_tail_hashes = fixed_tail_hashes or set()
    excluded_terminal: list[tuple[int, Path]] = []
    while ordered_local and file_sha256(ordered_local[-1][1]) in fixed_tail_hashes:
        excluded_terminal.insert(0, ordered_local.pop())
    body_local = ordered_local
    count_aligned = len(body_local) == len(refs)
    body_images: list[dict[str, Any]] = []
    missing_local: list[int] = []
    dimension_matches = 0
    for ref in refs:
        local_record = body_local[ref["body_index"] - 1] if ref["body_index"] <= len(body_local) else None
        if local_record is None:
            missing_local.append(ref["body_index"])
            body_images.append({**ref, "local_number": None, "local_path": None, "mapping_status": "missing_local"})
            continue
        number, local_path = local_record
        width, height = image_dimensions(local_path)
        html_profile = html_profiles[ref["body_index"] - 1] if ref["body_index"] <= len(html_profiles) else {}
        declared_width = html_profile.get("declared_width")
        declared_ratio = html_profile.get("declared_height_ratio")
        ratio_comparable = bool(width and height and declared_ratio is not None)
        ratio_matches = bool(ratio_comparable and abs((height / width) - declared_ratio) <= 0.02)
        if ratio_matches:
            dimension_matches += 1
        mapping_status = "mapped"
        mapping_confidence = "order_and_ratio" if ratio_matches else "order_only"
        if not count_aligned:
            mapping_status = "candidate_manual"
            mapping_confidence = "count_mismatch"
        elif ratio_comparable and not ratio_matches:
            mapping_status = "candidate_manual"
            mapping_confidence = "ratio_conflict"
        body_images.append(
            {
                **ref,
                "local_number": number,
                "local_path": str(local_path),
                "sha256": file_sha256(local_path),
                "width": width,
                "height": height,
                "html_declared_width": declared_width,
                "html_declared_height_ratio": declared_ratio,
                "dimension_check": "aspect_ratio_matched" if ratio_matches else "aspect_ratio_conflict" if ratio_comparable else "unverified",
                "mapping_status": mapping_status,
                "mapping_confidence": mapping_confidence,
            }
        )
    mapped = [item for item in body_images if item["mapping_status"] == "mapped"]
    sample_indices = sorted({1, max(1, (len(refs) + 1) // 2), len(refs)}) if refs else []
    sample_paths = [body_images[index - 1]["local_path"] for index in sample_indices if body_images[index - 1].get("local_path")]
    return {
        "article_path": str(path.resolve()),
        "html_path": str(html_path.resolve()) if html_path.is_file() else None,
        "timestamp": timestamp,
        "archive_title": archive_title,
        "body_boundary": body_boundary,
        "asset_directory": str(asset_dir) if asset_dir else None,
        "asset_directory_match_type": match_type,
        "cover_path": str(cover) if cover else None,
        "body_reference_count": len(refs),
        "mapped_body_image_count": len(mapped),
        "missing_body_indices": missing_local,
        "excluded_trailing_local_assets": [
            {
                "path": str(local_path),
                "sha256": file_sha256(local_path),
                "analysis_eligibility": "excluded",
                "excluded_asset_role": "fixed_terminal_candidate",
                "exclusion_evidence": "同一哈希在至少两篇文章中均连续占据末尾两个或更多本地资源位置；不作为正文顺序映射候选，语义角色仍需实际查看确认",
            }
            for _, local_path in excluded_terminal
        ],
        "unresolved_local_assets": [str(local_path) for _, local_path in body_local[len(refs) :]] if len(body_local) > len(refs) else [],
        "local_body_candidate_count": len(body_local),
        "local_reference_count_aligned": count_aligned,
        "html_dimension_matches": dimension_matches,
        "visual_sampling_candidates": sample_paths,
        "body_images": body_images,
    }


def detect_fixed_terminal_hashes(selection: dict[str, Any]) -> set[str]:
    articles_by_hash: dict[str, set[str]] = {}
    occurrences: dict[str, int] = {}
    for item in selection.get("selected", []):
        path = Path(item["path"])
        try:
            _, title = split_archive_stem(path)
        except ValueError:
            continue
        asset_dir, _ = find_article_asset_dir(path.parent / "图片", title)
        ordered = sorted(numbered_images(asset_dir).items()) if asset_dir else []
        if len(ordered) < 2:
            continue
        terminal_hash = file_sha256(ordered[-1][1])
        run = 0
        for _, local_path in reversed(ordered):
            if file_sha256(local_path) != terminal_hash:
                break
            run += 1
        if run < 2:
            continue
        articles_by_hash.setdefault(terminal_hash, set()).add(str(path.resolve()))
        occurrences[terminal_hash] = occurrences.get(terminal_hash, 0) + run
    return {value for value, paths in articles_by_hash.items() if len(paths) >= 2 and occurrences.get(value, 0) >= 4}


def build_mapping(selection: dict[str, Any]) -> dict[str, Any]:
    fixed_tail_hashes = detect_fixed_terminal_hashes(selection)
    articles = [map_article(Path(item["path"]), fixed_tail_hashes) for item in selection.get("selected", [])]
    total_refs = sum(item["body_reference_count"] for item in articles)
    total_mapped = sum(item["mapped_body_image_count"] for item in articles)
    trailing_paths = [Path(record["path"]) for item in articles for record in item.get("excluded_trailing_local_assets", []) if Path(record["path"]).is_file()]
    trailing_hashes: dict[str, list[str]] = {}
    for path in trailing_paths:
        trailing_hashes.setdefault(file_sha256(path), []).append(str(path.resolve()))
    repeated_trailing_groups = [paths for paths in trailing_hashes.values() if len(paths) > 1]
    return {
        "visual_mapping_version": "1.1",
        "mapping_method": "先用已确认的微信公众号正文边界限定Markdown图片引用。只有当同一哈希在至少两篇文章中都连续占据末尾两个或更多本地资源位置时，才把这些末尾文件排除为固定尾部资产候选；排除后，本地正文候选数必须与正文引用数相等，才允许按数字后缀顺序映射。再以同篇HTML唯一 #js_content 内图片 data-ratio 与本地像素宽高比逐张校验；比例冲突或数量不齐均转人工，不用尾图补位。",
        "coverage_boundary": "映射成功只证明图片属于该文且位置顺序可追溯；跨文章重复且位于正文引用之后，只能说明它是固定尾部资产候选，仍需实际查看后才能命名为二维码、关注卡或页脚。视觉角色、信息质量和版式判断均需语义审核。",
        "summary": {
            "articles": len(articles),
            "articles_with_confirmed_body_boundary": sum(1 for item in articles if (item.get("body_boundary") or {}).get("status") in {"confirmed_markers", "confirmed_js_content"}),
            "articles_with_cover": sum(1 for item in articles if item["cover_path"]),
            "body_references": total_refs,
            "mapped_body_images": total_mapped,
            "mapping_rate": round(total_mapped / total_refs, 4) if total_refs else 0,
            "html_dimension_matches": sum(item["html_dimension_matches"] for item in articles),
            "excluded_trailing_local_assets": len(trailing_paths),
            "repeated_trailing_asset_groups": len(repeated_trailing_groups),
            "repeated_trailing_asset_files": sum(len(paths) for paths in repeated_trailing_groups),
            "articles_requiring_manual_mapping": sum(1 for item in articles if not item.get("local_reference_count_aligned") or any(image.get("mapping_status") == "candidate_manual" for image in item.get("body_images", []))),
            "unresolved_local_assets": sum(len(item.get("unresolved_local_assets", [])) for item in articles),
        },
        "repeated_trailing_asset_groups": repeated_trailing_groups,
        "articles": articles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Map selected WeChat Markdown articles to downloaded cover and numbered body images.")
    parser.add_argument("selection", type=Path, help="sample_selection.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    mapping = build_mapping(load_json(args.selection))
    write_json(args.output, mapping)
    print(
        f"visual_mapping={args.output} articles={mapping['summary']['articles']} "
        f"mapped={mapping['summary']['mapped_body_images']}/{mapping['summary']['body_references']}"
    )


if __name__ == "__main__":
    main()
