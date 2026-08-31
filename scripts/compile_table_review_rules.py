from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _common import load_json, write_json
from prepare_table_reviews import VALID_ANALYSIS_ROLES, VALID_REVIEW_STATUS, sheet_id


def compile_rules(tables: dict[str, Any], sample: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    rules = policy.get("rules", [])
    if not isinstance(rules, list) or not rules:
        raise ValueError("policy.rules must be a non-empty list")
    selected_paths = {
        str(Path(str(item.get("path") or "")).resolve()).lower()
        for item in sample.get("selected", []) if item.get("path")
    }
    decisions: list[dict[str, Any]] = []
    unmatched: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    for workbook in tables.get("files", []):
        resolved = str(Path(str(workbook.get("path") or "")).resolve())
        if resolved.lower() not in selected_paths:
            continue
        workbook_name = Path(resolved).name
        for sheet in workbook.get("sheets", []):
            if int(sheet.get("nonempty_cells") or 0) == 0:
                continue
            name = str(sheet.get("name") or "")
            matches: list[tuple[int, dict[str, Any]]] = []
            for rule in rules:
                if re.search(str(rule.get("workbook_pattern") or ".*"), workbook_name, flags=re.I) and re.search(str(rule.get("sheet_pattern") or ".*"), name, flags=re.I):
                    matches.append((int(rule.get("priority") or 0), rule))
            if not matches:
                unmatched.append(f"{workbook_name}::{name}")
                continue
            highest = max(value[0] for value in matches)
            winners = [rule for priority, rule in matches if priority == highest]
            if len(winners) != 1:
                ambiguous.append({"sheet": f"{workbook_name}::{name}", "rule_ids": [str(rule.get("rule_id") or "") for rule in winners]})
                continue
            rule = winners[0]
            status = str(rule.get("review_status") or "reviewed")
            role = str(rule.get("analysis_role") or "")
            if status not in VALID_REVIEW_STATUS or role not in VALID_ANALYSIS_ROLES:
                raise ValueError(f"invalid rule decision: {rule.get('rule_id')}:{status}:{role}")
            can_support = rule.get("can_support_claims")
            if can_support is None:
                can_support = status == "reviewed" and role not in {"coding_template", "audience_voice_synthetic", "excluded_unrelated"}
            decisions.append({
                "sheet_id": sheet_id(resolved, name),
                "analysis_role": role,
                "review_status": status,
                "can_support_claims": bool(can_support),
                "decision_reason": str(rule.get("decision_reason") or ""),
                "source_kind": str(rule.get("source_kind") or "unknown"),
                "metric_scope": str(rule.get("metric_scope") or "not_applicable"),
                "reviewer": str(policy.get("reviewer") or "human_reviewed_policy"),
                "matched_rule_id": str(rule.get("rule_id") or ""),
            })
    return {
        "review_policy_version": "1.0",
        "reviewer": str(policy.get("reviewer") or "human_reviewed_policy"),
        "decisions": decisions,
        "checks": {"decisions": len(decisions), "unmatched": unmatched, "ambiguous": ambiguous},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand human-reviewed workbook/sheet rules into explicit per-sheet decisions.")
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="Fail when a non-empty selected sheet is unmatched or ambiguous.")
    args = parser.parse_args()
    result = compile_rules(load_json(args.tables), load_json(args.sample), load_json(args.policy))
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), **result["checks"]}, ensure_ascii=False))
    if args.strict and (result["checks"]["unmatched"] or result["checks"]["ambiguous"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
