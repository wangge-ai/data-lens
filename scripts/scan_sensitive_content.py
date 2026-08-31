from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from _common import read_text_fallback, write_json


TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".html", ".htm", ".xml", ".py", ".js", ".css"}
PATTERNS = [
    ("private_key", "high", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer_token", "high", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key", "high", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b")),
    ("password_assignment", "high", re.compile(r"(?:password|passwd|pwd|密码)\s*[:=：]\s*[^\s,;，；]{4,}", re.I)),
    ("mainland_phone", "medium", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("mainland_id", "medium", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")),
]


def iter_text_files(paths: Iterable[Path], max_bytes: int) -> list[Path]:
    files: set[Path] = set()
    for supplied in paths:
        if supplied.is_file():
            candidates = [supplied]
        elif supplied.is_dir():
            candidates = [item for item in supplied.rglob("*") if item.is_file()]
        else:
            raise FileNotFoundError(supplied)
        for path in candidates:
            if path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= max_bytes:
                files.add(path.resolve())
    return sorted(files, key=lambda value: str(value).lower())


def scan(paths: list[Path], max_bytes: int = 5 * 1024 * 1024) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    files = iter_text_files(paths, max_bytes)
    for path in files:
        text, encoding = read_text_fallback(path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for category, severity, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    fingerprint = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:16]
                    findings.append({
                        "path": str(path),
                        "line_number": line_number,
                        "category": category,
                        "severity": severity,
                        "match_fingerprint": fingerprint,
                        "value_logged": False,
                        "encoding": encoding,
                    })
    return {
        "sensitive_scan_version": "1.0",
        "coverage_boundary": "仅扫描限定大小的文本类文件；结果不保存匹配原值。二进制文档、图片和未转录音视频不在本次扫描范围内。",
        "summary": {
            "files_scanned": len(files),
            "findings": len(findings),
            "high": sum(1 for item in findings if item["severity"] == "high"),
            "medium": sum(1 for item in findings if item["severity"] == "medium"),
        },
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan report-bound text artifacts for likely secrets or personal identifiers without logging matched values.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--max-mb", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-high", action="store_true")
    args = parser.parse_args()
    result = scan(args.paths, args.max_mb * 1024 * 1024)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), **result["summary"]}, ensure_ascii=False))
    if args.fail_on_high and result["summary"]["high"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
