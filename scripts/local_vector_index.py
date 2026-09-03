from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from _common import ensure_output_not_source, file_sha256, read_text_fallback


TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".csv", ".tsv", ".json", ".jsonl"}
TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.I)
INDEX_CONTRACT = "data-lens-vector-index/1.0"


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


def _validated_index(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"metadata", "chunks"}.issubset(tables):
                return False
            row = connection.execute("SELECT value FROM metadata WHERE key = 'contract_version'").fetchone()
            return bool(row and json.loads(row[0]) == INDEX_CONTRACT)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError):
        return False


def _populate_index(database: Path, root: Path, files: list[Path], *, dimensions: int, chunk_chars: int, overlap: int) -> dict[str, Any]:
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
            "contract_version": INDEX_CONTRACT,
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


def build_index(source: Path, database: Path, *, dimensions: int = 384, chunk_chars: int = 1200, overlap: int = 120, replace: bool = False) -> dict[str, Any]:
    root, files = _source_files(source)
    ensure_output_not_source(database, files)
    previous_hash: str | None = None
    if database.exists():
        if not replace:
            raise FileExistsError(f"index already exists; pass --replace to rebuild: {database}")
        if not _validated_index(database):
            raise ValueError(f"--replace target is not a verified Data Lens vector index: {database}")
        previous_hash = file_sha256(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".tmp", dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        metadata = _populate_index(
            temporary,
            root,
            files,
            dimensions=dimensions,
            chunk_chars=chunk_chars,
            overlap=overlap,
        )
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        if previous_hash is None:
            if database.exists():
                raise FileExistsError(f"index appeared while building; refusing to overwrite: {database}")
        elif not database.exists() or file_sha256(database) != previous_hash or not _validated_index(database):
            raise RuntimeError(f"existing Data Lens vector index changed while rebuilding: {database}")
        os.replace(temporary, database)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ("-journal", "-wal", "-shm"):
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)


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
