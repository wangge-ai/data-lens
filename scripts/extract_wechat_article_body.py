from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from _common import read_text_fallback, write_json


BODY_START_MARKER = "去阅读"
BODY_END_MARKER = "预览时标签不可点"
FOOTER_CLUSTER_MARKERS = ("修改于", "微信扫一扫", "作者头像", "精选留言")
BLOCK_TAGS = {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"}
SKIP_TAGS = {"script", "style", "svg", "noscript"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def clean_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"[ \t\u00a0]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def trim_line_range(lines: list[str], start: int, end: int) -> tuple[int, int]:
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return start, end


def markdown_body(text: str, *, allow_fallback: bool = True) -> dict[str, Any]:
    lines = text.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.strip().startswith("#")), "")
    start_positions = [index for index, line in enumerate(lines) if line.strip() == BODY_START_MARKER]
    if len(start_positions) == 1:
        marker_start = start_positions[0]
        end_positions = []
        for index, line in enumerate(lines):
            if index <= marker_start or line.strip() != BODY_END_MARKER:
                continue
            lookahead = [candidate.strip() for candidate in lines[index + 1 : index + 8]]
            if "阅读" in lookahead:
                end_positions.append(index)
        if len(end_positions) == 1:
            marker_end = end_positions[0]
            start, end = trim_line_range(lines, marker_start + 1, marker_end)
            body = clean_text("\n".join(lines[start:end]))
            return {
                "body_text": body,
                "profile": "wechat_archive",
                "status": "confirmed_markers" if body else "empty_body",
                "requires_manual_confirmation": not bool(body),
                "start_marker": BODY_START_MARKER,
                "end_marker": BODY_END_MARKER,
                "origin_start_line": start + 1 if body else None,
                "origin_end_line": end if body else None,
                "excluded_prefix_lines": start,
                "excluded_suffix_lines": len(lines) - end,
                "title": title,
                "warnings": [] if body else ["正文边界存在，但边界内没有可用文本"],
            }

    if allow_fallback:
        candidates: list[int] = []
        for index, line in enumerate(lines):
            if line.strip() != "阅读":
                continue
            tail = "\n".join(lines[index + 1 : index + 41])
            hits = sum(1 for marker in FOOTER_CLUSTER_MARKERS if marker in tail)
            if hits >= 2:
                candidates.append(index)
        end = candidates[0] if len(candidates) == 1 else len(lines)
        fallback_marker = "阅读+页尾标记簇" if len(candidates) == 1 else None
        start, end = trim_line_range(lines, 0, end)
        body = clean_text("\n".join(lines[start:end]))
        warning = (
            "只找到‘阅读+页尾标记簇’回退边界；当前结果只能用于试样，正式报告前必须人工确认或用配对HTML交叉验证"
            if len(candidates) == 1
            else "未找到唯一、可复核的微信公众号正文边界；不得把整页内容当作作者正文"
        )
        return {
            "body_text": body if len(candidates) == 1 else "",
            "profile": "wechat_archive",
            "status": "fallback_requires_confirmation" if body and len(candidates) == 1 else "boundary_ambiguous_or_missing",
            "requires_manual_confirmation": True,
            "start_marker": None,
            "end_marker": fallback_marker,
            "origin_start_line": start + 1 if body and len(candidates) == 1 else None,
            "origin_end_line": end if body and len(candidates) == 1 else None,
            "excluded_prefix_lines": start,
            "excluded_suffix_lines": len(lines) - end,
            "title": title,
            "warnings": [warning],
        }

    return {
        "body_text": "",
        "profile": "wechat_archive",
        "status": "boundary_missing",
        "requires_manual_confirmation": True,
        "start_marker": None,
        "end_marker": None,
        "origin_start_line": None,
        "origin_end_line": None,
        "excluded_prefix_lines": 0,
        "excluded_suffix_lines": 0,
        "title": title,
        "warnings": ["未找到微信公众号正文起止标记"],
    }


class WechatContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active_tags: list[str] = []
        self.skip_depth = 0
        self.found = False
        self.found_count = 0
        self.parts: list[str] = []
        self.images: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {str(key).lower(): value for key, value in attrs}
        if not self.active_tags:
            if values.get("id") == "js_content":
                self.active_tags = [tag]
                self.found = True
                self.found_count += 1
            return
        if tag not in VOID_TAGS:
            self.active_tags.append(tag)
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "img":
            self.images.append(
                {
                    "remote_reference": values.get("data-src") or values.get("data-original") or values.get("src"),
                    "declared_width": values.get("data-w") or values.get("width"),
                    "declared_height_ratio": values.get("data-ratio"),
                    "alt": values.get("alt"),
                }
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.active_tags:
            return
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag not in VOID_TAGS and tag in self.active_tags:
            reverse_index = self.active_tags[::-1].index(tag)
            match_index = len(self.active_tags) - reverse_index - 1
            self.active_tags = self.active_tags[:match_index]

    def handle_data(self, data: str) -> None:
        if self.active_tags and not self.skip_depth:
            self.parts.append(data)


def html_js_content(text: str) -> dict[str, Any]:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(text, "html.parser")
        nodes = soup.select("#js_content")
        images: list[dict[str, Any]] = []
        body = ""
        if len(nodes) == 1:
            node = nodes[0]
            for skipped in node.find_all(list(SKIP_TAGS)):
                skipped.decompose()
            body = clean_text(node.get_text("\n"))
            for image in node.find_all("img"):
                images.append(
                    {
                        "remote_reference": image.get("data-src") or image.get("data-original") or image.get("src"),
                        "declared_width": image.get("data-w") or image.get("width"),
                        "declared_height_ratio": image.get("data-ratio"),
                        "alt": image.get("alt"),
                    }
                )
        confirmed = len(nodes) == 1 and bool(body)
        for item in images:
            for key in ("declared_width", "declared_height_ratio"):
                value = item.get(key)
                try:
                    item[key] = float(value) if value not in {None, ""} else None
                except (TypeError, ValueError):
                    item[key] = None
        return {
            "body_text": body,
            "profile": "wechat_archive",
            "status": "confirmed_js_content" if confirmed else "js_content_not_unique_or_empty",
            "requires_manual_confirmation": not confirmed,
            "start_marker": "#js_content" if nodes else None,
            "end_marker": "#js_content closing tag" if nodes else None,
            "origin_start_line": None,
            "origin_end_line": None,
            "excluded_prefix_lines": None,
            "excluded_suffix_lines": None,
            "title": "",
            "images": images,
            "parser_engine": "beautifulsoup_html_parser",
            "warnings": [] if confirmed else [f"HTML中 #js_content 数量为 {len(nodes)}，或正文为空；需要人工确认"],
        }
    except ImportError:
        pass

    parser = WechatContentParser()
    parser.feed(text)
    body = clean_text("".join(parser.parts))
    images = []
    for item in parser.images:
        normalized = dict(item)
        for key in ("declared_width", "declared_height_ratio"):
            value = normalized.get(key)
            try:
                normalized[key] = float(value) if value not in {None, ""} else None
            except (TypeError, ValueError):
                normalized[key] = None
        images.append(normalized)
    confirmed = parser.found_count == 1 and bool(body)
    return {
        "body_text": body,
        "profile": "wechat_archive",
        "status": "confirmed_js_content" if confirmed else "js_content_not_unique_or_empty",
        "requires_manual_confirmation": not confirmed,
        "start_marker": "#js_content" if parser.found else None,
        "end_marker": "#js_content closing tag" if parser.found else None,
        "origin_start_line": None,
        "origin_end_line": None,
        "excluded_prefix_lines": None,
        "excluded_suffix_lines": None,
        "title": "",
        "images": images,
        "parser_engine": "stdlib_html_parser",
        "warnings": [] if confirmed else [f"HTML中 #js_content 数量为 {parser.found_count}，或正文为空；需要人工确认"],
    }


def extract_wechat_article(path: Path, *, allow_fallback: bool = True) -> dict[str, Any]:
    text, encoding = read_text_fallback(path)
    suffix = path.suffix.lower()
    if suffix == ".md":
        result = markdown_body(text, allow_fallback=allow_fallback)
    elif suffix in {".html", ".htm", ".mhtml"}:
        result = html_js_content(text)
    else:
        result = {
            "body_text": "",
            "profile": "wechat_archive",
            "status": "unsupported_container",
            "requires_manual_confirmation": True,
            "warnings": [f"不支持的微信公众号正文容器：{suffix or '[无扩展名]'}"],
        }
    result.update({"source_path": str(path.resolve()), "source_encoding": encoding})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract the author body from a saved WeChat article without comments or page chrome.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    parser.add_argument("--no-fallback", action="store_true")
    args = parser.parse_args()
    result = extract_wechat_article(args.source, allow_fallback=not args.no_fallback)
    body = str(result.pop("body_text", ""))
    if body:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body + "\n", encoding="utf-8")
    write_json(args.json_report, {**result, "artifact_path": str(args.output.resolve()) if body else None})
    print(json.dumps({"status": result.get("status"), "body_chars": len(body), "output": str(args.output.resolve()) if body else None}, ensure_ascii=False))
    raise SystemExit(0 if body and not result.get("requires_manual_confirmation") else 2)


if __name__ == "__main__":
    main()
