from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text).strip().casefold()
    return re.sub(r"[\s_\-—–/\\]+", "", text)


def build_header_mapping(
    headers: list[Any],
    aliases: dict[str, tuple[str, ...]],
    *,
    adapter_version: str,
) -> dict[str, Any]:
    """Map semantic fields to source indexes and fail closed on drift.

    Every required field must match exactly one normalized header, and no
    source column may satisfy multiple semantic fields.
    """
    normalized = [normalize_header(value) for value in headers]
    mapping: dict[str, int] = {}
    for field, accepted in aliases.items():
        accepted_normalized = {normalize_header(value) for value in accepted}
        matches = [index for index, value in enumerate(normalized) if value and value in accepted_normalized]
        if not matches:
            raise ValueError(f"required header missing for {field}: {accepted!r}")
        if len(matches) > 1:
            raise ValueError(f"ambiguous header for {field}: columns {matches!r}")
        mapping[field] = matches[0]
    reverse: dict[int, list[str]] = {}
    for field, index in mapping.items():
        reverse.setdefault(index, []).append(field)
    collisions = {index: fields for index, fields in reverse.items() if len(fields) > 1}
    if collisions:
        raise ValueError(f"one source column maps to multiple fields: {collisions!r}")
    return {
        "adapter_version": adapter_version,
        "mapping": mapping,
        "source_headers": [None if value is None else str(value) for value in headers],
        "normalized_headers": normalized,
    }
