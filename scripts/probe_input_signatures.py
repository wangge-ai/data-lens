from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from _common import ExplicitInputAllowlist, guard_cli_output, load_json, write_json


MIN_SIGNATURE_BYTES = 12
MAX_SIGNATURE_BYTES = 4096


def signature_byte_count(value: str) -> int:
    try:
        byte_count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("signature byte count must be an integer") from exc
    if not MIN_SIGNATURE_BYTES <= byte_count <= MAX_SIGNATURE_BYTES:
        raise argparse.ArgumentTypeError(
            f"signature byte count must be between {MIN_SIGNATURE_BYTES} and {MAX_SIGNATURE_BYTES}"
        )
    return byte_count


def identify_signature(header: bytes) -> str:
    if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "ole_compound"
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip_container"
    if header.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "rar_archive"
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    if b"\x00" in header:
        return "binary_unknown"
    return "text_or_unknown"


def probe_inventory(
    inventory: dict[str, Any],
    byte_count: int = 32,
    *,
    scope: ExplicitInputAllowlist | None = None,
) -> dict[str, Any]:
    if not MIN_SIGNATURE_BYTES <= byte_count <= MAX_SIGNATURE_BYTES:
        raise ValueError(
            f"signature byte count must be between {MIN_SIGNATURE_BYTES} and {MAX_SIGNATURE_BYTES}"
        )
    scope = scope or ExplicitInputAllowlist.from_inventory(inventory)
    records = inventory.get("files", [])
    results: list[dict[str, Any]] = []
    detected = Counter()
    for record in records:
        path = scope.require(Path(str(record["path"])))
        header = scope.read_head(path, byte_count)
        signature = identify_signature(header)
        detected[signature] += 1
        results.append(
            {
                "source_container_id": record.get("source_container_id"),
                "extension": str(record.get("extension") or path.suffix).lower(),
                "signature": signature,
                "bytes_read": len(header),
            }
        )
    return {
        "probe_version": "1.1",
        "input_scope": "explicit_inventory_paths_only",
        "source_count": len(results),
        "summary": dict(sorted(detected.items())),
        "files": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe file signatures using only the concrete source paths in an existing Data Lens inventory."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bytes", type=signature_byte_count, default=32, dest="byte_count")
    args = parser.parse_args()
    inventory = load_json(args.inventory)
    scope = ExplicitInputAllowlist.from_inventory(inventory)
    guard_cli_output(parser, args.output, [args.inventory, *scope.paths])
    payload = probe_inventory(inventory, args.byte_count, scope=scope)
    write_json(args.output, payload)
    print(f"signature_probe={args.output} sources={payload['source_count']}")


if __name__ == "__main__":
    main()
