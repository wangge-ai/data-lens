from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from validate_mixed_workspace import read_jsonl


VALID_ENTITY_STATUS = {"confirmed", "candidate", "rejected"}
VALID_LINK_STATUS = {"confirmed", "candidate", "rejected"}
VALID_LINK_ROLES = {"input", "output", "delivery", "measured_result", "context", "unknown"}


def generated_entity_id(entity_type: str, label: str) -> str:
    return "ENT-" + hashlib.sha256(f"{entity_type}|{label}".encode("utf-8")).hexdigest()[:10]


def compile_entities(
    sample: dict[str, Any], evidence_rows: list[dict[str, Any]], decisions: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_ids = {str(item.get("source_container_id")) for item in sample.get("selected", [])}
    evidence_ids = {str(item.get("evidence_unit_id")) for item in evidence_rows}
    entities: list[dict[str, Any]] = []
    entity_ids: set[str] = set()
    entity_status_by_id: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for row in decisions.get("entities", []):
        entity_type = str(row.get("entity_type") or "").strip()
        label = str(row.get("label") or "").strip()
        status = str(row.get("status") or "candidate")
        if not entity_type or not label or status not in VALID_ENTITY_STATUS:
            raise ValueError("each entity requires entity_type, label, and a valid status")
        entity_id = str(row.get("entity_id") or generated_entity_id(entity_type, label))
        if entity_id in entity_ids:
            raise ValueError(f"duplicate entity_id: {entity_id}")
        entity_ids.add(entity_id)
        entity_status_by_id[entity_id] = status
        if label in aliases:
            raise ValueError(f"duplicate entity label: {label}")
        aliases[label] = entity_id
        entities.append({
            "entity_id": entity_id,
            "entity_type": entity_type,
            "label": label,
            "canonical_key": str(row.get("canonical_key") or label),
            "status": status,
            "boundary": str(row.get("boundary") or ""),
        })

    links: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in decisions.get("links", []):
        source_id = str(row.get("source_container_id") or "")
        entity_ref = str(row.get("entity_id") or row.get("entity_label") or "")
        entity_id = aliases.get(entity_ref, entity_ref)
        status = str(row.get("status") or "candidate")
        link_role = str(row.get("link_role") or "unknown")
        linked_evidence = sorted({str(value) for value in row.get("evidence_unit_ids", [])})
        reason = str(row.get("reason") or "").strip()
        match_scope = row.get("match_scope") or {}
        if source_id not in selected_ids:
            raise ValueError(f"entity link references unselected source: {source_id or '<missing>'}")
        if entity_id not in entity_ids:
            raise ValueError(f"entity link references unknown entity: {entity_ref or '<missing>'}")
        if status not in VALID_LINK_STATUS:
            raise ValueError(f"invalid entity link status: {source_id}:{status}")
        if link_role not in VALID_LINK_ROLES:
            raise ValueError(f"invalid entity link role: {source_id}:{link_role}")
        missing_evidence = [value for value in linked_evidence if value not in evidence_ids]
        if missing_evidence:
            raise ValueError(f"entity link evidence missing: {source_id}:{'|'.join(missing_evidence)}")
        if status == "confirmed" and (not linked_evidence or not reason):
            raise ValueError(f"confirmed entity link requires evidence and reason: {source_id}:{entity_id}")
        if status == "confirmed" and entity_status_by_id.get(entity_id) != "confirmed":
            raise ValueError(f"confirmed entity link requires a confirmed entity: {source_id}:{entity_id}")
        if status == "confirmed" and link_role == "measured_result":
            if not isinstance(match_scope, dict) or any(not str(match_scope.get(key) or "").strip() for key in ("object_version", "measurement_window", "platform")):
                raise ValueError(f"confirmed measured result link requires object_version, measurement_window, and platform: {source_id}:{entity_id}")
        pair = (source_id, entity_id)
        if pair in seen_pairs:
            raise ValueError(f"duplicate entity link: {source_id}:{entity_id}")
        seen_pairs.add(pair)
        links.append({
            "link_id": "EL-" + hashlib.sha256(f"{source_id}|{entity_id}".encode("utf-8")).hexdigest()[:10],
            "source_container_id": source_id,
            "entity_id": entity_id,
            "status": status,
            "link_role": link_role,
            "evidence_unit_ids": linked_evidence,
            "reason": reason,
            "boundary": str(row.get("boundary") or ""),
            "match_scope": match_scope,
        })
    return {"entity_registry_version": "1.0", "entities": entities}, links


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile reviewed project/product/course entity decisions and evidence-backed source links.")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--registry-output", type=Path, required=True)
    parser.add_argument("--links-output", type=Path, required=True)
    args = parser.parse_args()
    registry, links = compile_entities(load_json(args.sample), read_jsonl(args.evidence), load_json(args.decisions))
    write_json(args.registry_output, registry)
    write_jsonl(args.links_output, links)
    print(json.dumps({"registry": str(args.registry_output.resolve()), "links": str(args.links_output.resolve()), "entities": len(registry["entities"]), "confirmed_links": sum(1 for item in links if item["status"] == "confirmed")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
