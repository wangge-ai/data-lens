from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


SKILL_NAME = "data-lens"
SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILL_VERSION = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()

if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", SKILL_VERSION):
    raise RuntimeError("VERSION must contain one semantic version")


def normalize_title(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def parse_publish_stamp(name: str) -> tuple[str | None, str]:
    match = re.match(r"^\[(\d{8})(\d{4})?\](.+)$", name)
    if not match:
        return None, name
    return f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}", match.group(3)


def safe_number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    text = str(value).strip().replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ensure_output_not_source(output: Path, sources: Iterable[Path]) -> None:
    """Reject an output that resolves to a supplied source file.

    Directory inputs are checked against an existing destination inside the
    directory so a source discovered through recursive inventory cannot be
    overwritten. New output files inside a source directory remain allowed.
    """
    resolved_output = output.resolve()
    for source in sources:
        resolved_source = source.resolve()
        collision = resolved_output == resolved_source
        if not collision and resolved_source.is_dir() and resolved_output.exists():
            try:
                resolved_output.relative_to(resolved_source)
            except ValueError:
                pass
            else:
                collision = resolved_output.is_file()
        if collision:
            raise ValueError(f"output must not overwrite a source input: {resolved_output}")


def guard_cli_output(parser: Any, output: Path, sources: Iterable[Path]) -> None:
    try:
        ensure_output_not_source(output, sources)
    except ValueError as exc:
        parser.error(str(exc))


@contextmanager
def atomic_output_path(path: Path) -> Iterator[Path]:
    """Yield a same-directory temporary path and atomically publish it on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: Any) -> None:
    with atomic_output_path(path) as temporary:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8",
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text_fallback(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with atomic_output_path(path) as temporary:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})


def parse_date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    digits = re.sub(r"\.0$", "", text)
    if re.fullmatch(r"\d{8}", digits):
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
        except ValueError:
            return None
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    return None


def classify_title(title: str) -> str:
    if re.search(r"数据分析|市场洞察|商品评价|竞品分析|小数据中台|打法地图|评论分析", title, re.I):
        return "电商数据与分析"
    if re.search(r"主图|详情页|作图|电商图|生图|提示词|审美|image", title, re.I):
        return "电商视觉与作图"
    if re.search(r"小红书|微信文章|内容创作|微信群|视频|自媒体", title, re.I):
        return "内容与新媒体"
    if re.search(r"Codex|Claude|Agent|Workbuddy|GitHub|工具|智能体|Skill", title, re.I):
        return "AI工具与工作流"
    return "其他"


def title_features(title: str) -> dict[str, bool]:
    return {
        "has_number": bool(re.search(r"\d", title)),
        "has_first_person": bool(re.search(r"我用|我把|我拿|我整理|我拆|我搭|我做|我", title)),
        "has_tutorial": bool(re.search(r"教程|从0|保姆级|攻略|指南|完整", title, re.I)),
        "has_asset": bool(re.search(r"附|免费分享|开源|课件|资料包|SOP|Skill|报告|工作台", title, re.I)),
        "has_ecom": "电商" in title,
    }
