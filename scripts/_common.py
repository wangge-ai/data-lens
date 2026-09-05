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

_EXPLICIT_CAUSAL_WORDING = re.compile(
    r"(?:导致|造成|引发|促使|使得|致使|(?:令|让|使).{0,24}(?:更高|更低|更好|更差|"
    r"提高|提升|降低|下降|增加|减少|改善|恶化)|驱动|促进|抑制|决定了?|"
    r"带来|带动|拉高|拉低|有助于|助推|推动|催生|诱发|加剧|缓解|归因于|源于|源自|取决于|"
    r"(?:提升|提高|降低|增加|减少|改善|恶化)(?:了)?(?=[^\d\s%％，。；])|"
    r"\b(?:causes?|caused|causing|leads?\s+to|led\s+to|results?\s+in|resulted\s+in|"
    r"drives?|drove|effect\s+of|impact\s+of)\b)",
    re.IGNORECASE,
)
_EXPLICIT_PREDICTION_WORDING = re.compile(
    r"(?:(?:未来|下一(?:期|次|天|周|月|季|年|篇)|明天|明日|后续).{0,32}"
    r"(?:将|会|预计|预期|可望|有望|达到|升至|降至)|"
    r"(?:预计|预测|预期|将会|将达到|会达到|可望|有望).{0,32}(?:达到|升至|降至|为|增长|下降)|"
    r"(?:未来|下(?:期|次|天|周|月|季|年)|下一(?:期|次|天|周|月|季|年|篇)|明天|明日|后续).{0,32}"
    r"(?:\d+(?:\.\d+)?|盈利|亏损|增长|下降|上涨|下跌|高于|低于)|"
    r"\b(?:will|forecast(?:s|ed)?|is\s+expected\s+to|is\s+projected\s+to|next\s+period)\b)",
    re.IGNORECASE,
)
_EXPLICIT_ACTION_DIRECTIVE = re.compile(
    r"(?:(?:应当|应该|必须|务必|立即|马上|建议|宜|不妨|需要).{0,36}"
    r"(?:采用|执行|实施|停止|禁止|优先|设为|定为|改为|调整|投入|购买|上线|下线|推广|放弃|保留|扩大|缩小)|"
    r"(?:设为|定为).{0,16}(?:固定|默认|统一).{0,8}(?:规则|方案|策略)|"
    r"(?:以后|今后|后续|全部|全都|统一|固定|默认).{0,28}"
    r"(?:使用|采用|执行|实施|设为|定为|改为|上线|推广|停止|禁止|优先)|"
    r"(?:使用|采用|执行|实施|设为|定为|改为).{0,20}(?:统一|固定|默认)|"
    r"\b(?:should|must|recommend(?:s|ed)?|immediately|adopt|deploy|stop|ban)\b)",
    re.IGNORECASE,
)
_HYPOTHESIS_QUALIFIER = re.compile(
    r"(?:可能|或许|也许|假设|推测|候选机制|待检验|尚待验证|"
    r"\b(?:may|might|could|hypothesis|hypothesized|tentative|to\s+be\s+tested)\b)",
    re.IGNORECASE,
)
_NONCAUSAL_RELATION_WORDING = re.compile(
    r"(?:相关|关联|伴随|共变|共同变化|同步变化|反向变化|同时出现|差异|"
    r"\b(?:correlat(?:e|ed|es|ion)|associat(?:e|ed|es|ion)|co-?vary|difference)\b)",
    re.IGNORECASE,
)

if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", SKILL_VERSION):
    raise RuntimeError("VERSION must contain one semantic version")


def normalize_title(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def has_explicit_causal_wording(value: Any) -> bool:
    return bool(_EXPLICIT_CAUSAL_WORDING.search(str(value or "")))


def has_hypothesis_qualifier(value: Any) -> bool:
    return bool(_HYPOTHESIS_QUALIFIER.search(str(value or "")))


def has_explicit_prediction_wording(value: Any) -> bool:
    return bool(_EXPLICIT_PREDICTION_WORDING.search(str(value or "")))


def has_explicit_action_directive(value: Any) -> bool:
    return bool(_EXPLICIT_ACTION_DIRECTIVE.search(str(value or "")))


def has_noncausal_relation_wording(value: Any) -> bool:
    return bool(_NONCAUSAL_RELATION_WORDING.search(str(value or "")))


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


class InputNotAllowlistedError(ValueError):
    """Raised before a source is opened when it is outside the explicit input list."""


class ExplicitInputAllowlist:
    """Exact source-file scope for header, signature, MIME, and parser probes.

    Directory enumeration belongs to the inventory step. Later probes consume the
    inventory's concrete file paths through this object instead of searching a
    parent directory again.
    """

    def __init__(self, paths: Iterable[Path]) -> None:
        resolved: set[Path] = set()
        for path in paths:
            candidate = Path(path).resolve(strict=True)
            if not candidate.is_file():
                raise FileNotFoundError(f"allowlisted input is not a file: {candidate}")
            resolved.add(candidate)
        self._paths = frozenset(resolved)

    @classmethod
    def from_inventory(cls, inventory: dict[str, Any]) -> "ExplicitInputAllowlist":
        records = inventory.get("files")
        if not isinstance(records, list):
            raise ValueError("inventory.files must be a list")
        paths: list[Path] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict) or not str(record.get("path") or "").strip():
                raise ValueError(f"inventory.files[{index}].path is required")
            paths.append(Path(str(record["path"])))
        return cls(paths)

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self._paths, key=lambda path: str(path).lower()))

    def require(self, path: Path) -> Path:
        candidate = Path(path).resolve(strict=True)
        if candidate not in self._paths:
            raise InputNotAllowlistedError(f"source input is not explicitly allowlisted: {candidate}")
        return candidate

    @contextmanager
    def open_binary(self, path: Path) -> Iterator[Any]:
        candidate = self.require(path)
        with candidate.open("rb") as handle:
            yield handle

    def read_head(self, path: Path, byte_count: int = 32) -> bytes:
        if not 1 <= byte_count <= 4096:
            raise ValueError("byte_count must be between 1 and 4096")
        with self.open_binary(path) as handle:
            return handle.read(byte_count)

    def subprocess_path(self, path: Path) -> str:
        """Return a checked concrete path for Excel, ffprobe, or another local tool."""
        return str(self.require(path))


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


@contextmanager
def exclusive_output_reservation(path: Path, *, label: str = "output") -> Iterator[None]:
    """Reserve a new output name so concurrent or repeated runs cannot overwrite it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise FileExistsError(f"{label} already exists or is reserved by another run: {path.resolve()}") from exc
    os.close(descriptor)
    try:
        yield
    except BaseException:
        try:
            if path.is_file() and path.stat().st_size == 0:
                path.unlink()
        finally:
            raise


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
