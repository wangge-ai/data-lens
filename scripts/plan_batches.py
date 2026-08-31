from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, load_json, write_json


def digest(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def family_name(item: dict[str, Any]) -> str:
    return str(item.get("provisional_family") or item.get("category") or item.get("evidence_role") or "待识别资料")


def build_run_state(
    plan: dict[str, Any],
    inventory: dict[str, Any],
    sample: dict[str, Any],
    batch_size: int = 10,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    inventory_by_id = {
        str(item.get("source_container_id")): item
        for item in inventory.get("files", [])
        if item.get("canonical", True)
    }
    selected = list(sample.get("selected", []))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        groups[(family_name(item), str(item.get("evidence_role") or "unclassified"))].append(item)

    previous_batches = {str(item.get("artifact_fingerprint")): item for item in (previous or {}).get("batches", [])}
    previous_families = {str(item.get("label")): item for item in (previous or {}).get("families", [])}
    batches: list[dict[str, Any]] = []
    family_selected: dict[str, int] = defaultdict(int)
    family_lanes: dict[str, set[str]] = defaultdict(set)
    for (family, lane), members in sorted(groups.items()):
        ordered = sorted(members, key=lambda item: str(item.get("source_container_id") or item.get("path") or ""))
        for offset in range(0, len(ordered), batch_size):
            chunk = ordered[offset:offset + batch_size]
            source_ids = [str(item.get("source_container_id")) for item in chunk]
            source_fingerprints = [
                str(inventory_by_id.get(source_id, {}).get("sha256") or inventory_by_id.get(source_id, {}).get("modified_at") or source_id)
                for source_id in source_ids
            ]
            fingerprint = digest([SKILL_VERSION, str(plan.get("method_fingerprint") or plan.get("primary_route")), family, lane, *source_fingerprints])
            prior = previous_batches.get(fingerprint)
            reusable = bool(prior and prior.get("status") == "completed")
            batch_id = "B-" + fingerprint[:10]
            batches.append(
                {
                    "batch_id": batch_id,
                    "family": family,
                    "lane": lane,
                    "source_container_ids": source_ids,
                    "artifact_fingerprint": fingerprint,
                    "status": "reused" if reusable else "pending",
                    "reused_from": prior.get("batch_id") if reusable else None,
                    "output_artifacts": list(prior.get("output_artifacts") or []) if reusable else [],
                    "failure_reason": None,
                }
            )
            family_selected[family] += len(source_ids)
            family_lanes[family].add(lane)

    eligible_by_family = {str(item.get("family")): item.get("eligible_count") for item in sample.get("family_coverage", [])}
    eligibility_status_by_family = {
        str(item.get("family")): str(item.get("eligibility_status") or "known")
        for item in sample.get("family_coverage", [])
    }
    family_keys = sorted(set(eligible_by_family) | set(family_selected))
    families = []
    for family in family_keys:
        prior_family = previous_families.get(family, {})
        selected_count = family_selected.get(family, 0)
        eligible_value = eligible_by_family.get(family, selected_count)
        eligible_known = eligible_value is not None and eligibility_status_by_family.get(family, "known") == "known"
        eligible_count = int(eligible_value) if eligible_known else selected_count
        prior_selected = int(prior_family.get("selected_count") or 0)
        status = str(prior_family.get("status") or ("pending" if selected_count else "not_selected"))
        expansion_status = str(prior_family.get("expansion_status") or ("pilot_pending" if selected_count else "not_started"))
        if selected_count > prior_selected and expansion_status not in {"full_census_complete", "stable_two_batches"}:
            status = "pending"
            expansion_status = "expansion_batch_pending"
        families.append({
            "family_id": "FAM-" + hashlib.sha256(family.encode("utf-8")).hexdigest()[:10],
            "label": family,
            "eligible_count": eligible_count,
            "eligible_count_known": eligible_known,
            "selected_count": selected_count,
            "required_lanes": sorted(family_lanes.get(family, set())),
            "processed_count": int(prior_family.get("processed_count") or 0),
            "excluded_count": int(prior_family.get("excluded_count") or 0),
            "status": status,
            "expansion_status": expansion_status,
            "new_information_history": list(prior_family.get("new_information_history") or []),
            "reviewed_source_ids": list(prior_family.get("reviewed_source_ids") or []),
            "excluded_source_ids": list(prior_family.get("excluded_source_ids") or []),
        })
    inventory_fingerprint = digest(
        [
            str((inventory.get("summary") or {}).get("canonical_items") or len(inventory_by_id)),
            *sorted(str(item.get("sha256") or item.get("source_container_id")) for item in inventory_by_id.values()),
        ]
    )
    route = str(plan.get("primary_route") or "novel_route")
    selected_ids = sorted(str(item.get("source_container_id")) for item in selected)
    run_id = "RUN-" + digest([
        SKILL_VERSION, route, str(plan.get("method_fingerprint") or ""), inventory_fingerprint,
        str(sample.get("selection_version")), str(sample.get("strategy")), str(batch_size), *selected_ids,
    ])[:12]
    return {
        "run_state_version": "1.2",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "run_id": run_id,
        "supersedes_run_id": (previous or {}).get("run_id"),
        "route": route,
        "inventory_fingerprint": inventory_fingerprint,
        "batch_size": batch_size,
        "stages": {
            "inventory": "completed",
            "source_graph": "completed",
            "table_review": "pending",
            "semantic_review": "pending",
            "family_synthesis": "pending",
            "cross_family_synthesis": "pending",
            "report": "pending",
        },
        "families": families,
        "batches": batches,
        "excluded_sources": [],
        "resume_rule": "只复用来源指纹、Skill版本、路线和家族均未变化且已完成的批次；失败或待处理批次从最后保存的中间产物继续。",
        "expansion_rule": sample.get("expansion_rule") or "覆盖全部必要证据通道后，只有两个可比较批次都没有新增方法、条件、冲突或资料角色时，才可停止扩样并记录边界。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create resumable, family-aware semantic review batches for a mixed corpus.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_run_state(
        load_json(args.plan), load_json(args.inventory), load_json(args.sample), args.batch_size,
        load_json(args.previous) if args.previous else None,
    )
    write_json(args.output, result)
    print(f"run_state={args.output} run_id={result['run_id']} batches={len(result['batches'])}")


if __name__ == "__main__":
    main()
