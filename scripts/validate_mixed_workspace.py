from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from _common import load_json, write_json


VALID_LANES = {"content_text", "performance_table", "tabular_data", "visual_layout", "audience_voice", "temporal_metadata", "audio_video", "source_metadata", "unclassified"}
VALID_REVIEW = {"parsed", "matched", "ocr_complete", "semantically_reviewed"}
VALID_RELATION_STATUS = {"confirmed", "candidate", "rejected", "unrelated"}
VALID_RELATION_TYPES = {"source", "method", "prompt", "skill", "template", "output", "performance", "version", "sibling", "continuation", "unrelated", "unknown"}
VALID_BATCH_STATUS = {"pending", "completed", "failed", "excluded", "reused"}
VALID_STAGE_STATUS = {"pending", "in_progress", "completed", "failed"}
VALID_DIRECTNESS = {"direct", "derived", "inferred"}
VALID_DISPOSITIONS = {"analyzed", "excluded", "pending"}
VALID_ENTITY_STATUS = {"confirmed", "candidate", "rejected"}
VALID_ENTITY_LINK_ROLE = {"input", "output", "delivery", "measured_result", "context", "unknown"}
FORBIDDEN_DIRECT_ARTIFACTS = {"evidence_units.jsonl", "family_analyses.jsonl", "relations.jsonl", "deep_analysis.json"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        raise FileNotFoundError(str(path))
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number}:record_not_object")
        rows.append(value)
    return rows


def require_list(record: dict[str, Any], keys: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for key in keys:
        if not isinstance(record.get(key), list):
            errors.append(f"{prefix}_list_invalid:{record.get('id') or record.get('evidence_unit_id') or record.get('family_id') or record.get('relation_id') or '<missing>'}:{key}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def json_pointer(document: Any, pointer: str) -> Any:
    current = document
    if pointer in {"", "/"}:
        return current
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def version_at_least(value: str, minimum: tuple[int, int]) -> bool:
    match = re.match(r"^(\d+)\.(\d+)", value or "")
    return bool(match and (int(match.group(1)), int(match.group(2))) >= minimum)


def validate_trace(item: dict[str, Any], errors: list[str]) -> None:
    evidence_id = str(item.get("evidence_unit_id") or item.get("id") or "<missing>")
    trace = item.get("trace")
    if not isinstance(trace, dict):
        errors.append(f"evidence_trace_missing:{evidence_id}")
        return
    origin = Path(str(trace.get("origin_path") or ""))
    if not origin.is_file():
        errors.append(f"evidence_origin_missing:{evidence_id}:{origin}")
        return
    expected_origin_hash = str(trace.get("origin_sha256") or "")
    if not expected_origin_hash or sha256(origin) != expected_origin_hash:
        errors.append(f"evidence_origin_hash_mismatch:{evidence_id}")
    directness = str(trace.get("directness") or "")
    if directness not in VALID_DIRECTNESS:
        errors.append(f"evidence_directness_invalid:{evidence_id}:{directness}")

    locator = item.get("locator") or {}
    locator_type = locator.get("type")
    declared_source = Path(str(item.get("source_path") or "")) if item.get("source_path") else None
    if locator_type == "text_span":
        artifact = Path(str(locator.get("artifact_path") or ""))
        if not artifact.is_file():
            errors.append(f"evidence_artifact_missing:{evidence_id}:{artifact}")
            return
        if artifact.name in FORBIDDEN_DIRECT_ARTIFACTS:
            errors.append(f"evidence_self_authored_artifact_forbidden:{evidence_id}:{artifact.name}")
        if declared_source is not None and declared_source.resolve() != artifact.resolve():
            errors.append(f"evidence_source_artifact_mismatch:{evidence_id}")
        if str(trace.get("artifact_sha256") or "") != sha256(artifact):
            errors.append(f"evidence_artifact_hash_mismatch:{evidence_id}")
        lines = artifact.read_text(encoding="utf-8-sig").splitlines()
        try:
            start, end = int(locator.get("start_line")), int(locator.get("end_line"))
        except (TypeError, ValueError):
            errors.append(f"evidence_text_span_invalid:{evidence_id}")
            return
        if start < 1 or end < start or end > len(lines):
            errors.append(f"evidence_text_span_outside:{evidence_id}")
            return
        quote = str(locator.get("quote") or "")
        if not quote or norm(quote) not in norm("\n".join(lines[start - 1:end])):
            errors.append(f"evidence_text_quote_mismatch:{evidence_id}")
    elif locator_type == "table_extract":
        artifact = Path(str(locator.get("artifact_path") or ""))
        if not artifact.is_file():
            errors.append(f"evidence_table_artifact_missing:{evidence_id}:{artifact}")
            return
        if artifact.name in FORBIDDEN_DIRECT_ARTIFACTS:
            errors.append(f"evidence_self_authored_artifact_forbidden:{evidence_id}:{artifact.name}")
        if declared_source is not None and declared_source.resolve() != artifact.resolve():
            errors.append(f"evidence_source_artifact_mismatch:{evidence_id}")
        if str(trace.get("artifact_sha256") or "") != sha256(artifact):
            errors.append(f"evidence_artifact_hash_mismatch:{evidence_id}")
        try:
            actual = json_pointer(load_json(artifact), str(locator.get("json_pointer") or ""))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            errors.append(f"evidence_table_pointer_invalid:{evidence_id}")
            return
        quote = str(locator.get("quote") or "")
        if not quote or norm(quote) not in norm(json.dumps(actual, ensure_ascii=False)):
            errors.append(f"evidence_table_quote_mismatch:{evidence_id}")
    elif locator_type == "image":
        image_path = Path(str(locator.get("path") or ""))
        if not image_path.is_file() or image_path.resolve() != origin.resolve():
            errors.append(f"evidence_image_origin_mismatch:{evidence_id}")
        if declared_source is not None and declared_source.resolve() != image_path.resolve():
            errors.append(f"evidence_source_artifact_mismatch:{evidence_id}")
        if not locator.get("description"):
            errors.append(f"evidence_image_description_missing:{evidence_id}")
    elif locator_type == "pdf_pages":
        pages = locator.get("pages")
        if Path(str(locator.get("path") or "")).resolve() != origin.resolve() or not isinstance(pages, list) or not pages:
            errors.append(f"evidence_pdf_locator_invalid:{evidence_id}")
    elif locator_type == "video_frames":
        timestamps = locator.get("timestamps_seconds")
        if Path(str(locator.get("path") or "")).resolve() != origin.resolve() or not isinstance(timestamps, list) or not timestamps:
            errors.append(f"evidence_video_locator_invalid:{evidence_id}")
    else:
        errors.append(f"evidence_trace_locator_invalid:{evidence_id}:{locator_type}")


def validate_workspace(workspace: Path, allow_incomplete: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required_files = {
        "source_graph": workspace / "source_graph.json",
        "run_state": workspace / "run_state.json",
        "evidence_units": workspace / "evidence_units.jsonl",
        "family_analyses": workspace / "family_analyses.jsonl",
        "relations": workspace / "relations.jsonl",
    }
    for name, path in required_files.items():
        if not path.is_file():
            errors.append(f"workspace_artifact_missing:{name}:{path.name}")
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "counts": {}}

    graph = load_json(required_files["source_graph"])
    state = load_json(required_files["run_state"])
    strict_trace = version_at_least(str(state.get("skill_version") or ""), (0, 6))
    strict_dispositions = version_at_least(str(state.get("skill_version") or ""), (0, 7))
    dispositions_path = workspace / "source_dispositions.jsonl"
    if strict_dispositions and not dispositions_path.is_file():
        errors.append("workspace_artifact_missing:source_dispositions:source_dispositions.jsonl")
    dispositions = read_jsonl(dispositions_path) if dispositions_path.is_file() else []
    evidence = read_jsonl(required_files["evidence_units"])
    families = read_jsonl(required_files["family_analyses"])
    relations = read_jsonl(required_files["relations"])

    node_ids = [str(item.get("source_container_id") or "") for item in graph.get("nodes", [])]
    if any(not value for value in node_ids) or len(node_ids) != len(set(node_ids)):
        errors.append("source_graph_node_ids_invalid")
    node_id_set = set(node_ids)
    for edge in graph.get("edges", []):
        if edge.get("from_id") not in node_id_set or edge.get("to_id") not in node_id_set:
            errors.append(f"source_graph_edge_endpoint_missing:{edge.get('relation_id')}")

    for stage, status in (state.get("stages") or {}).items():
        if status not in VALID_STAGE_STATUS:
            errors.append(f"run_stage_status_invalid:{stage}:{status}")
    for batch in state.get("batches", []):
        batch_id = str(batch.get("batch_id") or "<missing>")
        if batch.get("status") not in VALID_BATCH_STATUS:
            errors.append(f"batch_status_invalid:{batch_id}:{batch.get('status')}")
        for source_id in batch.get("source_container_ids", []):
            if source_id not in node_id_set:
                errors.append(f"batch_source_missing:{batch_id}:{source_id}")
        if batch.get("status") == "failed" and not batch.get("failure_reason"):
            errors.append(f"batch_failure_reason_missing:{batch_id}")
    for item in state.get("excluded_sources", []):
        if item.get("source_container_id") not in node_id_set or not item.get("reason"):
            errors.append(f"excluded_source_invalid:{item.get('source_container_id')}")

    evidence_ids: set[str] = set()
    observed_source_ids: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("evidence_unit_id") or "")
        if not evidence_id or evidence_id in evidence_ids:
            errors.append(f"evidence_unit_id_invalid:{evidence_id or '<missing>'}")
        evidence_ids.add(evidence_id)
        source_id = str(item.get("source_container_id") or "")
        if source_id not in node_id_set:
            errors.append(f"evidence_unit_source_missing:{evidence_id}:{source_id}")
        else:
            observed_source_ids.add(source_id)
        for key in ("family_id", "unit_type", "locator", "sensitivity", "allowed_use"):
            if item.get(key) in (None, "", {}):
                errors.append(f"evidence_unit_incomplete:{evidence_id}:{key}")
        if item.get("lane") not in VALID_LANES:
            errors.append(f"evidence_unit_lane_invalid:{evidence_id}:{item.get('lane')}")
        if item.get("review_status") not in VALID_REVIEW:
            errors.append(f"evidence_unit_review_invalid:{evidence_id}:{item.get('review_status')}")
        require_list(item, ("observed_facts", "interpretations", "cannot_prove"), "evidence_unit", errors)
        if not item.get("observed_facts"):
            errors.append(f"evidence_unit_facts_empty:{evidence_id}")
        if not item.get("cannot_prove"):
            errors.append(f"evidence_unit_boundary_empty:{evidence_id}")
        if item.get("lane") == "visual_layout" and item.get("review_status") != "semantically_reviewed":
            errors.append(f"visual_evidence_not_semantically_reviewed:{evidence_id}")
        if strict_trace:
            validate_trace(item, errors)
            if len(item.get("observed_facts") or []) != 1:
                errors.append(f"evidence_unit_not_atomic:{evidence_id}:{len(item.get('observed_facts') or [])}")
            if (item.get("interpretations") or []) == ["该来源用于确认本资料族的内容角色和成熟度。"]:
                errors.append(f"evidence_unit_generic_interpretation:{evidence_id}")

    family_ids: set[str] = set()
    for item in families:
        family_id = str(item.get("family_id") or "")
        if not family_id or family_id in family_ids:
            errors.append(f"family_analysis_id_invalid:{family_id or '<missing>'}")
        family_ids.add(family_id)
        for key in ("label", "method_route", "comparison_unit", "coverage", "status"):
            if item.get(key) in (None, "", {}):
                errors.append(f"family_analysis_incomplete:{family_id}:{key}")
        require_list(
            item,
            ("source_container_ids", "evidence_unit_ids", "common_patterns", "differences", "version_relations", "reusable_methods", "conflicts", "boundaries"),
            "family_analysis",
            errors,
        )
        for source_id in item.get("source_container_ids", []):
            if source_id not in node_id_set:
                errors.append(f"family_analysis_source_missing:{family_id}:{source_id}")
        for evidence_id in item.get("evidence_unit_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"family_analysis_evidence_missing:{family_id}:{evidence_id}")
        if not item.get("boundaries"):
            errors.append(f"family_analysis_boundaries_empty:{family_id}")

    entity_ids: set[str] = set()
    rejected_entity_ids: set[str] = set()
    confirmed_entity_ids: set[str] = set()
    entity_registry_path = workspace / "entity_registry.json"
    entity_links_path = workspace / "source_entity_links.jsonl"
    entity_links: list[dict[str, Any]] = []
    if entity_registry_path.is_file():
        registry = load_json(entity_registry_path)
        for item in registry.get("entities", []):
            entity_id = str(item.get("entity_id") or "")
            status = str(item.get("status") or "")
            link_role = str(item.get("link_role") or "unknown")
            if not entity_id or entity_id in entity_ids:
                errors.append(f"entity_id_invalid:{entity_id or '<missing>'}")
                continue
            entity_ids.add(entity_id)
            if not item.get("entity_type") or not item.get("label") or status not in VALID_ENTITY_STATUS:
                errors.append(f"entity_incomplete:{entity_id}")
            if status == "rejected":
                rejected_entity_ids.add(entity_id)
            elif status == "confirmed":
                confirmed_entity_ids.add(entity_id)
        if not entity_links_path.is_file():
            errors.append("entity_links_missing_for_registry")
    if entity_links_path.is_file():
        if not entity_registry_path.is_file():
            errors.append("entity_registry_missing_for_links")
        entity_links = read_jsonl(entity_links_path)
        seen_links: set[str] = set()
        for item in entity_links:
            link_id = str(item.get("link_id") or "")
            source_id = str(item.get("source_container_id") or "")
            entity_id = str(item.get("entity_id") or "")
            status = str(item.get("status") or "")
            if not link_id or link_id in seen_links:
                errors.append(f"entity_link_id_invalid:{link_id or '<missing>'}")
            seen_links.add(link_id)
            if source_id not in node_id_set or entity_id not in entity_ids:
                errors.append(f"entity_link_endpoint_missing:{link_id}")
            if status not in VALID_ENTITY_STATUS:
                errors.append(f"entity_link_status_invalid:{link_id}:{status}")
            if link_role not in VALID_ENTITY_LINK_ROLE:
                errors.append(f"entity_link_role_invalid:{link_id}:{link_role}")
            linked_evidence = item.get("evidence_unit_ids")
            if not isinstance(linked_evidence, list):
                errors.append(f"entity_link_evidence_list_invalid:{link_id}")
                linked_evidence = []
            for evidence_id in linked_evidence:
                if evidence_id not in evidence_ids:
                    errors.append(f"entity_link_evidence_missing:{link_id}:{evidence_id}")
            if status == "confirmed" and (not linked_evidence or not item.get("reason") or entity_id in rejected_entity_ids):
                errors.append(f"entity_link_confirmed_invalid:{link_id}")
            if status == "confirmed" and entity_id not in confirmed_entity_ids:
                errors.append(f"entity_link_confirmed_to_unconfirmed_entity:{link_id}")
            if status == "confirmed" and link_role == "measured_result":
                scope = item.get("match_scope") or {}
                if not isinstance(scope, dict) or any(not str(scope.get(key) or "").strip() for key in ("object_version", "measurement_window", "platform")):
                    errors.append(f"entity_result_scope_incomplete:{link_id}")

    relation_ids: set[str] = set()
    valid_relation_entities = node_id_set | family_ids | entity_ids
    for item in relations:
        relation_id = str(item.get("relation_id") or "")
        if not relation_id or relation_id in relation_ids:
            errors.append(f"semantic_relation_id_invalid:{relation_id or '<missing>'}")
        relation_ids.add(relation_id)
        if item.get("from_id") not in valid_relation_entities or item.get("to_id") not in valid_relation_entities:
            errors.append(f"semantic_relation_endpoint_missing:{relation_id}")
        if item.get("relation_type") not in VALID_RELATION_TYPES:
            errors.append(f"semantic_relation_type_invalid:{relation_id}:{item.get('relation_type')}")
        if item.get("status") not in VALID_RELATION_STATUS:
            errors.append(f"semantic_relation_status_invalid:{relation_id}:{item.get('status')}")
        require_list(item, ("evidence_unit_ids",), "semantic_relation", errors)
        for evidence_id in item.get("evidence_unit_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"semantic_relation_evidence_missing:{relation_id}:{evidence_id}")
        if item.get("status") == "confirmed" and not item.get("evidence_unit_ids"):
            errors.append(f"semantic_relation_confirmed_without_evidence:{relation_id}")
        if item.get("status") == "confirmed" and (item.get("from_id") in rejected_entity_ids or item.get("to_id") in rejected_entity_ids):
            errors.append(f"semantic_relation_confirmed_with_rejected_entity:{relation_id}")
        if not item.get("rationale") or not item.get("boundary"):
            errors.append(f"semantic_relation_reasoning_incomplete:{relation_id}")

    selected_source_ids = {
        str(source_id)
        for batch in state.get("batches", [])
        for source_id in batch.get("source_container_ids", [])
    }
    excluded_source_ids = {str(item.get("source_container_id")) for item in state.get("excluded_sources", [])}
    disposition_by_source: dict[str, dict[str, Any]] = {}
    for item in dispositions:
        source_id = str(item.get("source_container_id") or "")
        disposition = str(item.get("disposition") or "")
        if not source_id or source_id in disposition_by_source:
            errors.append(f"source_disposition_id_invalid:{source_id or '<missing>'}")
            continue
        disposition_by_source[source_id] = item
        if source_id not in selected_source_ids:
            errors.append(f"source_disposition_outside_selection:{source_id}")
        if disposition not in VALID_DISPOSITIONS:
            errors.append(f"source_disposition_invalid:{source_id}:{disposition}")
        if disposition == "analyzed" and source_id not in observed_source_ids:
            errors.append(f"source_disposition_analyzed_without_evidence:{source_id}")
        if disposition == "excluded" and not item.get("reason"):
            errors.append(f"source_disposition_exclusion_reason_missing:{source_id}")
    ledger_excluded = {source_id for source_id, item in disposition_by_source.items() if item.get("disposition") == "excluded"}
    if strict_dispositions and ledger_excluded != excluded_source_ids:
        errors.append("source_disposition_exclusions_not_synchronized")
    missing_semantic = selected_source_ids - observed_source_ids - excluded_source_ids
    semantic_done = (state.get("stages") or {}).get("semantic_review") == "completed"
    unfinished_batches = [item for item in state.get("batches", []) if item.get("status") not in {"completed", "reused", "excluded"}]
    if semantic_done and unfinished_batches and not allow_incomplete:
        errors.append(f"semantic_stage_completed_with_unfinished_batches:{len(unfinished_batches)}")
    if missing_semantic:
        message = f"selected_sources_without_disposition:{len(missing_semantic)}"
        (errors if semantic_done and not allow_incomplete else warnings).append(message)
    if strict_dispositions:
        missing_dispositions = selected_source_ids - set(disposition_by_source)
        pending_dispositions = {source_id for source_id, item in disposition_by_source.items() if item.get("disposition") == "pending"}
        if missing_dispositions:
            message = f"selected_sources_without_disposition_record:{len(missing_dispositions)}"
            (errors if semantic_done and not allow_incomplete else warnings).append(message)
        if pending_dispositions:
            message = f"selected_sources_pending_disposition:{len(pending_dispositions)}"
            (errors if semantic_done and not allow_incomplete else warnings).append(message)

    planned_families = {str(item.get("family_id")) for item in state.get("families", []) if item.get("selected_count", 0) > 0}
    family_done = (state.get("stages") or {}).get("family_synthesis") == "completed"
    missing_family = planned_families - family_ids
    if missing_family:
        message = f"planned_families_without_analysis:{len(missing_family)}"
        (errors if family_done and not allow_incomplete else warnings).append(message)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "source_nodes": len(node_ids),
            "selected_sources": len(selected_source_ids),
            "evidence_units": len(evidence),
            "family_analyses": len(families),
            "semantic_relations": len(relations),
            "source_dispositions": len(dispositions),
            "entities": len(entity_ids),
            "entity_links": len(entity_links),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Data Lens mixed-corpus intermediate artifacts and their references.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    result = validate_workspace(args.workspace, args.allow_incomplete)
    if args.json_report:
        write_json(args.json_report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
