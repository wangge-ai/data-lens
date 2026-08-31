from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import file_sha256, load_json, write_json


def initialize(workspace: Path, title: str, subtitle: str, report_mode: str, depth: str) -> dict:
    inventory = load_json(workspace / "inventory.json")
    sample = load_json(workspace / "sample_selection.json")
    plan = load_json(workspace / "analysis_plan.json")
    gate_path = workspace / "run_gate_validation.json"
    if not gate_path.is_file():
        raise FileNotFoundError("run_gate_validation.json must exist before initializing deep_analysis")
    gate = load_json(gate_path)
    if not gate.get("valid") or gate.get("report_mode") != report_mode or gate.get("report_depth") != depth:
        raise ValueError("run gate does not authorize the requested report mode/depth")
    canonical = int((inventory.get("summary") or {}).get("canonical_items") or 0)
    selected = int(sample.get("selected_count") or 0)
    return {
        "contract_version": "2.3", "completion_status": report_mode, "report_depth": depth,
        "route": plan.get("primary_route"), "title": title, "subtitle": subtitle,
        "run_gate": {"validation_path": str(gate_path.resolve()), "sha256": file_sha256(gate_path)},
        "analysis_units": {
            "source_container_unit": "待确认", "analysis_unit": "待确认", "unit_status": "provisional",
            "source_container_count": canonical, "eligible_count": canonical, "selected_count": selected,
            "observed_count": 0, "missing_count": 0, "unselected_count": max(0, canonical - selected),
            "unreadable_count": 0, "not_applicable_count": 0,
            "deduplication_rule": "来自 inventory.json，待在语义审阅后确认。",
            "version_rule": "版本候选必须经正文或元数据确认。",
            "grouping_rule": "先按业务角色和证据通道分组。",
        },
        "presentation": {}, "analysis_intent": {}, "scope": {}, "sampling": {}, "evidence_coverage": [],
        "analysis_checklist": [], "metric_definitions": [], "executive_summary": [], "evidence": [],
        "findings": [], "comparisons": [], "analysis_sections": [], "recommendations": [], "experiments": [],
        "limitations": [], "unanswered_questions": [], "method": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a gate-bound Data Lens deep_analysis 2.3 artifact.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--report-mode", choices=["final", "preliminary"], required=True)
    parser.add_argument("--depth", choices=["brief", "standard", "deep"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = initialize(args.workspace, args.title, args.subtitle, args.report_mode, args.depth)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "contract_version": "2.3"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
