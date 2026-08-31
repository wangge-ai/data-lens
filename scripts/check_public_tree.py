from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "runtime", "outputs", "dist", "build"}
FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pyc", ".pyo"}
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
PRIVATE_PATH_PATTERNS = [
    re.compile(r"(?i)\b[A-Z]:\\Users\\(?!Alice\\secret\.txt)"),
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile("/" + r"home/[^/\s]+/"),
]


def scan() -> list[str]:
    errors: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith(".env"):
            errors.append(f"forbidden public file: {relative.as_posix()}")
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            errors.append(f"unexpected file larger than 5 MiB: {relative.as_posix()}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                errors.append(f"non-UTF-8 text or unexpected binary: {relative.as_posix()}")
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible secret in {relative.as_posix()}: {pattern.pattern}")
        for pattern in PRIVATE_PATH_PATTERNS:
            if pattern.search(text):
                errors.append(f"private absolute path in {relative.as_posix()}: {pattern.pattern}")
    return errors


def main() -> None:
    errors = scan()
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print("public tree guard passed")


if __name__ == "__main__":
    main()
