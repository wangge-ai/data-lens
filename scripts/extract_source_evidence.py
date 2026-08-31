from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from _common import file_sha256, load_json, read_text_fallback, write_json
from extract_wechat_article_body import BODY_END_MARKER, BODY_START_MARKER, extract_wechat_article


TEXT_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json", ".py", ".js", ".css", ".csv", ".tsv"}


class VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip += 1
        elif tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self.skip:
            self.skip -= 1
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def clean_text(value: str) -> str:
    value = html.unescape(value).replace("\x00", "")
    value = re.sub(r"[ \t\u00a0]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def extract_html(path: Path) -> str:
    parser = VisibleHTML()
    parser.feed(read_text_fallback(path)[0])
    return clean_text("".join(parser.parts))


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    chunks: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            chunks.append(node.text)
        elif node.tag.endswith("}p"):
            chunks.append("\n")
    return clean_text(" ".join(chunks))


def extract_pptx(path: Path) -> str:
    slides: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=natural_key,
        )
        for index, name in enumerate(names, start=1):
            root = ET.fromstring(archive.read(name))
            texts = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
            if texts:
                slides.append(f"[第{index}页] " + " | ".join(texts))
    return clean_text("\n".join(slides))


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = [f"[第{index}页]\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages, start=1)]
        return clean_text("\n\n".join(pages))
    except Exception:
        return ""


def inspect_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
    suffixes = Counter(Path(item.filename).suffix.lower() or "[无扩展名]" for item in members)
    roots = Counter(item.filename.replace("\\", "/").split("/", 1)[0] for item in members)
    largest = sorted(((item.file_size, item.filename) for item in members), reverse=True)[:30]
    return "\n".join([
        f"压缩包文件数: {len(members)}",
        "扩展名分布: " + ", ".join(f"{key}={value}" for key, value in suffixes.most_common()),
        "顶层目录: " + ", ".join(f"{key}={value}" for key, value in roots.most_common()),
        "大文件样本:",
        *(f"- {size} bytes | {name}" for size, name in largest),
    ])


def extract(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return clean_text(read_text_fallback(path)[0]), "direct_text"
    if suffix in {".html", ".htm", ".mhtml"}:
        return extract_html(path), "html_visible_text"
    if suffix == ".docx":
        return extract_docx(path), "docx_xml"
    if suffix == ".pptx":
        return extract_pptx(path), "pptx_xml"
    if suffix == ".pdf":
        return extract_pdf(path), "pdf_text"
    if suffix == ".zip":
        return inspect_zip(path), "zip_manifest"
    return "", "unsupported_requires_lane_specific_review"


def extract_with_profile(path: Path, source_profile: str) -> tuple[str, str, dict[str, Any] | None]:
    if source_profile not in {"auto", "generic", "wechat_archive"}:
        raise ValueError(f"unsupported source profile: {source_profile}")
    raw_text = read_text_fallback(path)[0] if path.suffix.lower() in {".md", ".html", ".htm", ".mhtml"} else ""
    detected_wechat = (
        path.suffix.lower() == ".md" and BODY_START_MARKER in raw_text and BODY_END_MARKER in raw_text
    ) or (
        path.suffix.lower() in {".html", ".htm", ".mhtml"} and re.search(r"\bid=[\"']js_content[\"']", raw_text, re.I) is not None
    )
    if source_profile == "wechat_archive" or (source_profile == "auto" and detected_wechat):
        result = extract_wechat_article(path, allow_fallback=source_profile == "wechat_archive")
        body = str(result.pop("body_text", ""))
        method = "wechat_markdown_markers" if result.get("status") == "confirmed_markers" else "wechat_html_js_content" if result.get("status") == "confirmed_js_content" else "wechat_boundary_requires_review"
        return body, method, result
    text, method = extract(path)
    return text, method, None


def build_extracts(sample: dict[str, Any], output_dir: Path, max_chars: int, source_profile: str = "auto") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for item in sample.get("selected", []):
        origin = Path(str(item.get("path") or ""))
        if not origin.is_file():
            records.append({
                "source_container_id": item.get("source_container_id"), "origin_path": str(origin),
                "status": "origin_missing", "extraction_method": "none",
            })
            continue
        text, method, boundary = extract_with_profile(origin, source_profile)
        original_chars = len(text)
        stored = text[:max_chars]
        source_id = str(item.get("source_container_id") or file_sha256(origin)[:12])
        artifact = output_dir / f"{source_id}.txt"
        if stored:
            artifact.write_text(stored + ("\n" if not stored.endswith("\n") else ""), encoding="utf-8")
        if stored and boundary and boundary.get("requires_manual_confirmation"):
            status = "parsed_requires_boundary_review"
        else:
            status = "parsed" if stored else "empty_requires_lane_specific_review"
        records.append({
            "source_container_id": source_id,
            "title": item.get("title") or origin.stem,
            "origin_path": str(origin.resolve()),
            "origin_sha256": file_sha256(origin),
            "origin_size_bytes": origin.stat().st_size,
            "evidence_role": item.get("evidence_role"),
            "business_role": item.get("business_role"),
            "provisional_family": item.get("provisional_family"),
            "extraction_method": method,
            "status": status,
            "original_char_count": original_chars,
            "stored_char_count": len(stored),
            "truncated": original_chars > len(stored),
            "artifact_path": str(artifact.resolve()) if stored else None,
            "artifact_sha256": file_sha256(artifact) if stored else None,
            "line_count": len(artifact.read_text(encoding="utf-8").splitlines()) if stored else 0,
            "body_boundary": boundary,
        })
    payload = {
        "content_extract_version": "1.1",
        "source_profile": source_profile,
        "coverage_boundary": "抽取物只用于可定位引用；origin_path 与 origin_sha256 才是原始来源。微信公众号正文只有在起止标记或 #js_content 被确认后才能排除页面控件和评论；回退边界必须人工确认。空文本必须转视觉/OCR/音视频路线，不能用模型补写。",
        "records": records,
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Create deterministic, origin-hashed text extracts for selected Data Lens sources.")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=120_000)
    parser.add_argument("--source-profile", choices=("auto", "generic", "wechat_archive"), default="auto")
    args = parser.parse_args()
    result = build_extracts(load_json(args.sample), args.output_dir, args.max_chars, args.source_profile)
    print(json.dumps({
        "output": str((args.output_dir / "manifest.json").resolve()),
        "records": len(result["records"]),
        "parsed": sum(1 for item in result["records"] if item.get("status") == "parsed"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
