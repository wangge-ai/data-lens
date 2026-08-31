from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from _common import file_sha256, read_text_fallback


TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".csv", ".tsv", ".json", ".jsonl"}
TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.I)


def _tokens(text: str) -> list[str]:
    base = [token.lower() for token in TOKEN_RE.findall(text)]
    chinese = [token for token in base if len(token) == 1 and "\u4e00" <= token <= "\u9fff"]
    return base + [chinese[index] + chinese[index + 1] for index in range(len(chinese) - 1)]


def hashing_vector(text: str, dimensions: int) -> dict[int, float]:
    values: dict[int, float] = {}
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        values[index] = values.get(index, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {index: value / norm for index, value in values.items()} if norm else {}


def _dot(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def _chunks(text: str, max_chars: int, overlap: int) -> Iterable[tuple[int, int, str]]:
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + max_chars)
        if end < length:
            boundary = max(text.rfind("\n", start + max_chars // 2, end), text.rfind("。", start + max_chars // 2, end))
            if boundary > start:
                end = boundary + 1
        excerpt = text[start:end].strip()
        if excerpt:
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            yield start + leading, start + leading + len(excerpt), excerpt
        if end >= length:
            break
        start = max(start + 1, end - overlap)


def _source_files(source: Path) -> tuple[Path, list[Path]]:
    if source.is_file():
        if source.suffix.lower() not in TEXT_EXTENSIONS:
            raise ValueError(f"unsupported text source: {source.suffix}")
        return source.parent, [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS)
    return source, files


def build_index(source: Path, database: Path, *, dimensions: int = 384, chunk_chars: int = 1200, overlap: int = 120, replace: bool = False) -> dict[str, Any]:
    if database.exists() and not replace:
        raise FileExistsError(f"index already exists; pass --replace to rebuild: {database}")
    root, files = _source_files(source)
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE chunks (
              chunk_id TEXT PRIMARY KEY,
              source_path TEXT NOT NULL,
              source_sha256 TEXT NOT NULL,
              char_start INTEGER NOT NULL,
              char_end INTEGER NOT NULL,
              excerpt TEXT NOT NULL,
              vector_json TEXT NOT NULL
            );
            """
        )
        chunk_count = 0
        for path in files:
            text, _ = read_text_fallback(path)
            source_hash = file_sha256(path)
            relative = path.relative_to(root).as_posix()
            for char_start, char_end, excerpt in _chunks(text, chunk_chars, overlap):
                vector = hashing_vector(excerpt, dimensions)
                chunk_id = hashlib.sha256(f"{source_hash}:{char_start}:{char_end}".encode("utf-8")).hexdigest()[:24]
                connection.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (chunk_id, relative, source_hash, char_start, char_end, excerpt, json.dumps(vector, separators=(",", ":"))),
                )
                chunk_count += 1
        metadata = {
            "contract_version": "data-lens-vector-index/1.0",
            "backend": "local_sqlite_hashing",
            "dimensions": dimensions,
            "chunk_chars": chunk_chars,
            "overlap": overlap,
            "source_file_count": len(files),
            "chunk_count": chunk_count,
            "source_of_truth": False,
        }
        for key, value in metadata.items():
            connection.execute("INSERT INTO metadata VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
        connection.commit()
        return metadata
    finally:
        connection.close()


def query_index(database: Path, text: str, *, limit: int = 10) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    connection = sqlite3.connect(database)
    try:
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM metadata")}
        dimensions = int(metadata["dimensions"])
        query_vector = hashing_vector(text, dimensions)
        results: list[dict[str, Any]] = []
        for row in connection.execute("SELECT chunk_id, source_path, source_sha256, char_start, char_end, excerpt, vector_json FROM chunks"):
            vector = {int(key): float(value) for key, value in json.loads(row[6]).items()}
            score = _dot(query_vector, vector)
            if score <= 0:
                continue
            results.append(
                {
                    "chunk_id": row[0],
                    "score": round(score, 8),
                    "source_path": row[1],
                    "source_sha256": row[2],
                    "locator": {"type": "text_span", "char_start": row[3], "char_end": row[4]},
                    "excerpt": row[5],
                    "status": "retrieval_candidate_only",
                }
            )
        results.sort(key=lambda item: (-item["score"], item["source_path"], item["locator"]["char_start"]))
        return {
            "contract_version": "data-lens-vector-query/1.0",
            "query": text,
            "backend": metadata.get("backend"),
            "source_of_truth": False,
            "boundary": "Retrieval hits locate candidates only; they do not prove prevalence, completeness, truth, or independent evidence.",
            "results": results[:limit],
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or query a local, rebuildable Data Lens vector index.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("source", type=Path)
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--dimensions", type=int, default=384)
    build.add_argument("--chunk-chars", type=int, default=1200)
    build.add_argument("--overlap", type=int, default=120)
    build.add_argument("--replace", action="store_true")
    query = subparsers.add_parser("query")
    query.add_argument("--database", type=Path, required=True)
    query.add_argument("--text", required=True)
    query.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.command == "build":
        if args.dimensions < 32 or args.dimensions > 4096:
            parser.error("--dimensions must be between 32 and 4096")
        if args.overlap < 0 or args.overlap >= args.chunk_chars:
            parser.error("--overlap must be non-negative and smaller than --chunk-chars")
        payload = build_index(args.source, args.database, dimensions=args.dimensions, chunk_chars=args.chunk_chars, overlap=args.overlap, replace=args.replace)
    else:
        payload = query_index(args.database, args.text, limit=args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
