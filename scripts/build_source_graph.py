from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, load_json, write_json


TECHNICAL_RELATIONS = {"variant", "exact_duplicate", "possible_version", "possible_continuation", "same_capture_session"}
SEMANTIC_RELATIONS = {"source", "method", "prompt", "skill", "template", "output", "performance", "version", "sibling", "unrelated", "unknown"}
VALID_RELATIONS = TECHNICAL_RELATIONS | SEMANTIC_RELATIONS
VALID_STATUS = {"confirmed", "candidate", "rejected", "unrelated"}


def stable_edge_id(source_id: str, target_id: str, relation_type: str) -> str:
    seed = f"{source_id}|{target_id}|{relation_type}".encode("utf-8")
    return "REL-" + hashlib.sha256(seed).hexdigest()[:12]


def build_graph(inventory: dict[str, Any], manual_relations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = list(inventory.get("files", []))
    path_to_id = {str(item.get("path")): str(item.get("source_container_id")) for item in records}
    nodes = [
        {
            "source_container_id": str(item.get("source_container_id")),
            "path": item.get("path"),
            "title": item.get("title") or item.get("name"),
            "canonical": bool(item.get("canonical", True)),
            "sha256": item.get("sha256"),
            "evidence_role": item.get("evidence_role") or "unclassified",
            "container_type": item.get("container_type") or "file",
            "asset_role": "unassigned",
            "current_status": "unknown",
            "sensitivity": "unreviewed",
            "allowed_use": "unreviewed",
        }
        for item in records
    ]
    node_ids = {item["source_container_id"] for item in nodes}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(source_id: str | None, target_id: str | None, relation_type: str, status: str, basis: str, **extra: Any) -> None:
        if not source_id or not target_id or source_id not in node_ids or target_id not in node_ids or source_id == target_id:
            return
        key = (source_id, target_id, relation_type)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "relation_id": stable_edge_id(source_id, target_id, relation_type),
                "from_id": source_id,
                "to_id": target_id,
                "relation_type": relation_type,
                "status": status,
                "basis": basis,
                **extra,
            }
        )

    for item in records:
        source_id = str(item.get("source_container_id"))
        if item.get("variant_of"):
            add_edge(source_id, path_to_id.get(str(item["variant_of"])), "variant", "confirmed", "canonical_format_selection")
        if item.get("exact_duplicate_of"):
            add_edge(source_id, path_to_id.get(str(item["exact_duplicate_of"])), "exact_duplicate", "confirmed", "sha256_match")

    for key_name, relation_type, basis in (
        ("source_family_key", "possible_version", "filename_family_hint"),
        ("possible_sequence_key", "possible_continuation", "numbered_sequence_hint"),
        ("capture_session_key", "same_capture_session", "timestamp_session_hint"),
    ):
        groups: dict[str, list[str]] = defaultdict(list)
        for item in records:
            if not item.get("canonical", True) or not item.get(key_name):
                continue
            groups[str(item[key_name])].append(str(item.get("source_container_id")))
        for members in groups.values():
            ordered = sorted(set(members))
            for target_id in ordered[1:]:
                add_edge(ordered[0], target_id, relation_type, "candidate", basis)

    for item in manual_relations or []:
        relation_type = str(item.get("relation_type") or "")
        status = str(item.get("status") or "candidate")
        if relation_type not in VALID_RELATIONS:
            raise ValueError(f"invalid relation_type: {relation_type}")
        if status not in VALID_STATUS:
            raise ValueError(f"invalid relation status: {status}")
        add_edge(
            str(item.get("from_id") or ""),
            str(item.get("to_id") or ""),
            relation_type,
            status,
            str(item.get("basis") or "manual_semantic_review"),
            evidence_unit_ids=list(item.get("evidence_unit_ids") or []),
            rationale=str(item.get("rationale") or ""),
            boundary=str(item.get("boundary") or ""),
        )

    return {
        "source_graph_version": "1.0",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "nodes": len(nodes),
            "canonical_nodes": sum(1 for item in nodes if item["canonical"]),
            "confirmed_edges": sum(1 for item in edges if item["status"] == "confirmed"),
            "candidate_edges": sum(1 for item in edges if item["status"] == "candidate"),
        },
        "boundary": "自动边只证明文件副本、文件名版本候选、连续页候选或同批截图。方法、成品、表现和上下游关系必须由语义证据确认。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an auditable source and lineage graph without inventing semantic relationships.")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--manual-relations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manual_payload = load_json(args.manual_relations) if args.manual_relations else []
    manual_relations = manual_payload.get("relations", []) if isinstance(manual_payload, dict) else manual_payload
    result = build_graph(load_json(args.inventory), manual_relations)
    write_json(args.output, result)
    print(f"source_graph={args.output} nodes={result['summary']['nodes']} edges={len(result['edges'])}")


if __name__ == "__main__":
    main()
