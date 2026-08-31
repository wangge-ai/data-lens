from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json, write_json
from validate_mixed_workspace import validate_trace


VALID_DEPTHS = {"brief", "standard", "deep"}
VALID_CLASSES = {"fact", "calculation", "inference", "hypothesis"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_COVERAGE_STATUS = {"available", "partial", "uninspected", "missing", "not_required"}
VALID_PROCESSING_STATES = {"source_only", "parsed", "pixel_readable", "ocr_complete", "semantically_reviewed", "matched"}
VALID_REVIEW_STATUS = {"parsed", "matched", "ocr_complete", "semantically_reviewed"}
VALID_UNIT_STATUS = {"provisional", "confirmed"}
VALID_CHECKLIST_STATUS = {"answered", "evidence_missing", "not_applicable"}
VALID_METRIC_TYPES = {"exact", "proxy", "descriptive_count"}
VALID_ROUTES = {"same_author_content", "account_content_performance", "method_corpus", "mixed_corpus", "novel_route"}
ROUTE_CHECKLISTS = {
    "same_author_content": {
        "topic_selection", "title_hook", "opening_structure", "body_structure", "writing_style",
        "visual_layout", "conversion_design", "exceptions",
    },
    "account_content_performance": {
        "metric_scope", "matching_coverage", "performance_distribution", "high_low_content_clues",
        "counterexamples", "confounders", "experiments",
    },
    "method_corpus": {
        "unit_definition", "method_steps", "conditions", "outcomes", "evidence_strength",
        "conflicts", "failure_boundaries", "next_action",
    },
    "mixed_corpus": {
        "family_definition", "lane_boundaries", "family_patterns", "family_differences",
        "version_and_component_relations", "cross_family_relations", "unrelated_items",
        "coverage_and_saturation", "next_action",
    },
    "novel_route": {
        "decision_question", "unit_definition", "evidence_boundaries", "patterns", "counterexamples", "next_action",
    },
}


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return document
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value)).replace("（", "(").replace("）", ")")


def validate_evidence(item: dict[str, Any], errors: list[str], strict_trace: bool = False) -> None:
    if strict_trace:
        validate_trace(item, errors)
        return
    evidence_id = item.get("id", "<missing>")
    source = Path(item.get("source_path", ""))
    if not source.is_file():
        errors.append(f"evidence_source_missing:{evidence_id}:{source}")
        return
    locator = item.get("locator") or {}
    kind = locator.get("type")
    try:
        if kind == "line_range":
            lines = source.read_text(encoding="utf-8-sig").splitlines()
            start, end = int(locator["start"]), int(locator["end"])
            if start < 1 or end < start or end > len(lines):
                errors.append(f"evidence_line_range_invalid:{evidence_id}")
                return
            quote = item.get("quote")
            if quote and norm(quote) not in norm("\n".join(lines[start - 1:end])):
                errors.append(f"evidence_quote_mismatch:{evidence_id}")
        elif kind == "json_pointer":
            actual = json_pointer(load_json(source), locator["pointer"])
            if "expected" in locator and actual != locator["expected"]:
                errors.append(f"evidence_json_value_mismatch:{evidence_id}")
        elif kind == "csv_row":
            with source.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            row_number = int(locator["row"])
            if row_number < 1 or row_number > len(rows):
                errors.append(f"evidence_csv_row_invalid:{evidence_id}")
            elif locator.get("key") and str(rows[row_number - 1].get(locator["key"])) != str(locator.get("expected")):
                errors.append(f"evidence_csv_value_mismatch:{evidence_id}")
        elif kind == "image":
            description = locator.get("description")
            if not description:
                errors.append(f"evidence_image_description_missing:{evidence_id}")
            region = locator.get("region")
            if region is not None:
                if not isinstance(region, list) or len(region) != 4 or any(not isinstance(value, (int, float)) for value in region):
                    errors.append(f"evidence_image_region_invalid:{evidence_id}")
                elif any(value < 0 for value in region) or region[2] <= 0 or region[3] <= 0:
                    errors.append(f"evidence_image_region_invalid:{evidence_id}")
                else:
                    try:
                        from PIL import Image  # type: ignore

                        with Image.open(source) as image:
                            width, height = image.size
                        if region[0] + region[2] > width or region[1] + region[3] > height:
                            errors.append(f"evidence_image_region_outside:{evidence_id}")
                    except ImportError:
                        pass
                    except Exception as exc:
                        errors.append(f"evidence_image_unreadable:{evidence_id}:{type(exc).__name__}")
        else:
            errors.append(f"evidence_locator_invalid:{evidence_id}:{kind}")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append(f"evidence_locator_error:{evidence_id}:{type(exc).__name__}")


def validate_analysis(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required = ("contract_version", "report_depth", "route", "title", "subtitle", "presentation", "scope", "executive_summary", "evidence", "findings", "comparisons", "analysis_sections", "recommendations", "limitations", "unanswered_questions", "method")
    for key in required:
        if key not in data:
            errors.append(f"missing_top_level:{key}")
    depth = data.get("report_depth")
    contract_version = str(data.get("contract_version") or "")
    if depth not in VALID_DEPTHS:
        errors.append(f"invalid_depth:{depth}")
    if data.get("route") not in VALID_ROUTES:
        errors.append(f"invalid_route:{data.get('route')}")
    if data.get("route") == "account_content_performance" and depth != "deep":
        errors.append("account_content_performance_requires_deep")

    presentation = data.get("presentation") or {}
    if not presentation.get("kicker") or not presentation.get("header_metrics") or not presentation.get("toc_groups"):
        errors.append("presentation_incomplete")
    valid_anchors = {"summary", "scope", "coverage", "findings", "comparisons", "actions", "experiments"}
    valid_anchors.update(f"section-{item.get('id')}" for item in data.get("analysis_sections", []))
    forbidden_nav = {"口径与覆盖", "完整发现", "成对比较", "限制与未知", "方法与证据", "方法与证据位置"}
    seen_anchors: set[str] = set()
    for group in presentation.get("toc_groups", []):
        if not group.get("label") or not group.get("items"):
            errors.append("presentation_toc_group_incomplete")
        for item in group.get("items", []):
            anchor, label = item.get("anchor"), item.get("label")
            if not anchor or not label:
                errors.append("presentation_toc_item_incomplete")
            elif anchor not in valid_anchors:
                errors.append(f"presentation_toc_anchor_invalid:{anchor}")
            if anchor in seen_anchors:
                errors.append(f"presentation_toc_anchor_duplicate:{anchor}")
            seen_anchors.add(anchor)
            if label in forbidden_nav:
                errors.append(f"presentation_toc_internal_label:{label}")

    if contract_version in {"2.1", "2.2", "2.3"}:
        for key in ("analysis_intent", "sampling", "evidence_coverage", "experiments"):
            if key not in data:
                errors.append(f"missing_top_level:{key}")
        intent = data.get("analysis_intent") or {}
        for key in ("decision_question", "primary_question", "requested_dimensions", "required_evidence", "available_evidence"):
            if intent.get(key) in (None, "", []):
                errors.append(f"analysis_intent_incomplete:{key}")
        for key in ("excluded_dimensions", "unresolved_choices"):
            if key not in intent or not isinstance(intent.get(key), list):
                errors.append(f"analysis_intent_list_missing:{key}")

        sampling = data.get("sampling") or {}
        for key in ("strategy", "requested_count", "eligible_count", "selected_count", "inclusion_rule", "exclusions", "bias_warnings"):
            if key not in sampling or sampling.get(key) in (None, ""):
                errors.append(f"sampling_incomplete:{key}")
        for key in ("requested_count", "eligible_count", "selected_count"):
            if not isinstance(sampling.get(key), int) or sampling.get(key, -1) < 0:
                errors.append(f"sampling_count_invalid:{key}")
        if isinstance(sampling.get("selected_count"), int) and isinstance(sampling.get("eligible_count"), int) and sampling["selected_count"] > sampling["eligible_count"]:
            errors.append("sampling_selected_exceeds_eligible")
        if not isinstance(sampling.get("exclusions"), (dict, list)):
            errors.append("sampling_exclusions_invalid")
        if not isinstance(sampling.get("bias_warnings"), list):
            errors.append("sampling_bias_warnings_invalid")

        coverage = data.get("evidence_coverage") or []
        if not coverage:
            errors.append("evidence_coverage_empty")
        seen_lanes: set[str] = set()
        for item in coverage:
            lane = str(item.get("lane") or "")
            if not lane or lane in seen_lanes:
                errors.append(f"evidence_coverage_lane_invalid:{lane or '<missing>'}")
            seen_lanes.add(lane)
            for key in ("status", "items", "proves", "cannot_prove"):
                if item.get(key) in (None, ""):
                    errors.append(f"evidence_coverage_incomplete:{lane}:{key}")
            if item.get("status") not in VALID_COVERAGE_STATUS:
                errors.append(f"evidence_coverage_status_invalid:{lane}:{item.get('status')}")
            if contract_version in {"2.2", "2.3"}:
                states = item.get("processing_states")
                if not isinstance(states, list) or not states:
                    errors.append(f"evidence_coverage_processing_missing:{lane}")
                elif any(state not in VALID_PROCESSING_STATES for state in states):
                    errors.append(f"evidence_coverage_processing_invalid:{lane}")

    metric_ids: set[str] = set()
    if contract_version in {"2.2", "2.3"}:
        units = data.get("analysis_units")
        if not isinstance(units, dict):
            errors.append("analysis_units_missing")
        else:
            for key in (
                "source_container_unit", "analysis_unit", "unit_status", "source_container_count",
                "eligible_count", "selected_count", "observed_count", "missing_count",
                "deduplication_rule", "version_rule", "grouping_rule",
            ):
                if units.get(key) in (None, ""):
                    errors.append(f"analysis_units_incomplete:{key}")
            if units.get("unit_status") not in VALID_UNIT_STATUS:
                errors.append(f"analysis_units_status_invalid:{units.get('unit_status')}")
            for key in ("source_container_count", "eligible_count", "selected_count", "observed_count", "missing_count"):
                if not isinstance(units.get(key), int) or units.get(key, -1) < 0:
                    errors.append(f"analysis_units_count_invalid:{key}")
            if isinstance(units.get("selected_count"), int) and isinstance(units.get("eligible_count"), int) and units["selected_count"] > units["eligible_count"]:
                errors.append("analysis_units_selected_exceeds_eligible")
            if isinstance(units.get("observed_count"), int) and isinstance(units.get("selected_count"), int) and units["observed_count"] > units["selected_count"]:
                errors.append("analysis_units_observed_exceeds_selected")

        metrics = data.get("metric_definitions")
        if not isinstance(metrics, list):
            errors.append("metric_definitions_invalid")
            metrics = []
        for metric in metrics:
            metric_id = str(metric.get("id") or "")
            if not metric_id:
                errors.append("metric_id_missing")
                continue
            if metric_id in metric_ids:
                errors.append(f"metric_id_duplicate:{metric_id}")
            metric_ids.add(metric_id)
            for key in (
                "label", "metric_type", "unit", "numerator", "denominator", "eligibility_rule",
                "missing_policy", "exclusions", "source_lane", "algorithm_version",
                "validity_conditions", "interpretation_limit",
            ):
                if metric.get(key) in (None, "", []):
                    errors.append(f"metric_incomplete:{metric_id}:{key}")
            if metric.get("metric_type") not in VALID_METRIC_TYPES:
                errors.append(f"metric_type_invalid:{metric_id}")
            if not isinstance(metric.get("validity_conditions"), list):
                errors.append(f"metric_validity_conditions_invalid:{metric_id}")
            label = str(metric.get("label") or "")
            validity = set(metric.get("validity_conditions") or [])
            if (label.endswith("胜率") or label.endswith("收益率")) and not {"entry_rule", "exit_rule", "cost_rule"}.issubset(validity):
                errors.append(f"metric_financial_label_unsupported:{metric_id}")
            if label.endswith("转化率") and (str(metric.get("numerator") or "").lower() in {"unknown", "未知"} or str(metric.get("denominator") or "").lower() in {"unknown", "未知"}):
                errors.append(f"metric_conversion_label_unsupported:{metric_id}")

    if contract_version == "2.3":
        completion_status = data.get("completion_status")
        if completion_status not in {"final", "preliminary"}:
            errors.append(f"completion_status_invalid:{completion_status}")
        gate = data.get("run_gate")
        if not isinstance(gate, dict):
            errors.append("run_gate_missing")
        else:
            gate_path = Path(str(gate.get("validation_path") or ""))
            if not gate_path.is_file():
                errors.append(f"run_gate_file_missing:{gate_path}")
            else:
                if str(gate.get("sha256") or "") != file_sha256(gate_path):
                    errors.append("run_gate_hash_mismatch")
                gate_data = load_json(gate_path)
                if not gate_data.get("valid") or not gate_data.get("report_eligible"):
                    errors.append("run_gate_not_eligible")
                if gate_data.get("report_mode") != completion_status:
                    errors.append("run_gate_mode_mismatch")
                if gate_data.get("report_depth") != depth:
                    errors.append("run_gate_depth_mismatch")
                if gate_data.get("route") and gate_data.get("route") != data.get("route"):
                    errors.append("run_gate_route_mismatch")
                for item in gate_data.get("inputs") or []:
                    role = str(item.get("role") or "unknown")
                    input_path = Path(str(item.get("path") or ""))
                    if not input_path.is_file():
                        errors.append(f"run_gate_input_missing:{role}")
                        continue
                    if str(item.get("sha256") or "") != file_sha256(input_path):
                        errors.append(f"run_gate_input_hash_mismatch:{role}")
        units = data.get("analysis_units") or {}
        for key in ("unselected_count", "unreadable_count", "not_applicable_count"):
            if not isinstance(units.get(key), int) or units.get(key, -1) < 0:
                errors.append(f"analysis_units_count_invalid:{key}")
        if isinstance(units.get("source_container_count"), int) and isinstance(units.get("selected_count"), int) and isinstance(units.get("unselected_count"), int):
            if units["selected_count"] + units["unselected_count"] > units["source_container_count"]:
                errors.append("analysis_units_selection_partition_invalid")

    collections = {name: data.get(name, []) for name in ("evidence", "findings", "comparisons", "recommendations")}
    id_sets: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for name, items in collections.items():
        ids = [str(item.get("id", "")) for item in items]
        if any(not value for value in ids):
            errors.append(f"missing_id:{name}")
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate_id:{name}")
        overlap = all_ids.intersection(ids)
        if overlap:
            errors.append(f"id_reused_across_types:{','.join(sorted(overlap))}")
        id_sets[name] = set(ids)
        all_ids.update(ids)

    for item in data.get("evidence", []):
        validate_evidence(item, errors, strict_trace=contract_version == "2.3")
        if contract_version in {"2.2", "2.3"}:
            evidence_id = item.get("id", "<missing>")
            for key in ("lane", "review_status", "source_family"):
                if item.get(key) in (None, ""):
                    errors.append(f"evidence_metadata_missing:{evidence_id}:{key}")
            if item.get("review_status") not in VALID_REVIEW_STATUS:
                errors.append(f"evidence_review_status_invalid:{evidence_id}:{item.get('review_status')}")
            if (item.get("locator") or {}).get("type") == "image" and item.get("review_status") != "semantically_reviewed":
                errors.append(f"evidence_image_not_semantically_reviewed:{evidence_id}")

    for finding in data.get("findings", []):
        fid = finding.get("id", "<missing>")
        for key in ("title", "fact", "explanation", "counterexamples", "boundaries", "recommendation_ids", "evidence_ids", "classification", "confidence"):
            if key not in finding or finding.get(key) in (None, "", []):
                errors.append(f"finding_incomplete:{fid}:{key}")
        if finding.get("classification") not in VALID_CLASSES:
            errors.append(f"finding_class_invalid:{fid}")
        if finding.get("confidence") not in VALID_CONFIDENCE:
            errors.append(f"finding_confidence_invalid:{fid}")
        for key in ("counterexamples", "boundaries", "recommendation_ids", "evidence_ids"):
            if key in finding and not isinstance(finding.get(key), list):
                errors.append(f"finding_list_invalid:{fid}:{key}")
        if contract_version in {"2.2", "2.3"} and finding.get("classification") == "calculation":
            if (data.get("analysis_units") or {}).get("unit_status") != "confirmed":
                errors.append(f"finding_calculation_requires_confirmed_unit:{fid}")
            if not isinstance(finding.get("metric_ids"), list) or not finding.get("metric_ids"):
                errors.append(f"finding_metric_missing:{fid}")
            for metric_id in finding.get("metric_ids", []):
                if metric_id not in metric_ids:
                    errors.append(f"finding_metric_unknown:{fid}:{metric_id}")
        for evidence_id in finding.get("evidence_ids", []):
            if evidence_id not in id_sets.get("evidence", set()):
                errors.append(f"finding_evidence_missing:{fid}:{evidence_id}")
        for recommendation_id in finding.get("recommendation_ids", []):
            if recommendation_id not in id_sets.get("recommendations", set()):
                errors.append(f"finding_recommendation_missing:{fid}:{recommendation_id}")

    for comparison in data.get("comparisons", []):
        cid = comparison.get("id", "<missing>")
        for key in ("title", "left", "right", "interpretation", "counterexample", "boundary", "evidence_ids"):
            if key not in comparison or comparison.get(key) in (None, "", []):
                errors.append(f"comparison_incomplete:{cid}:{key}")
        if not isinstance(comparison.get("left"), dict) or not isinstance(comparison.get("right"), dict):
            errors.append(f"comparison_sides_invalid:{cid}")
        if not isinstance(comparison.get("evidence_ids"), list):
            errors.append(f"comparison_evidence_list_invalid:{cid}")
        for evidence_id in comparison.get("evidence_ids", []):
            if evidence_id not in id_sets.get("evidence", set()):
                errors.append(f"comparison_evidence_missing:{cid}:{evidence_id}")

    for recommendation in data.get("recommendations", []):
        rid = recommendation.get("id", "<missing>")
        for key in ("title", "action", "rationale", "finding_ids", "validation_metric", "timebox", "risks", "fallback"):
            if key not in recommendation or recommendation.get(key) in (None, "", []):
                errors.append(f"recommendation_incomplete:{rid}:{key}")
        for key in ("finding_ids", "risks"):
            if key in recommendation and not isinstance(recommendation.get(key), list):
                errors.append(f"recommendation_list_invalid:{rid}:{key}")
        for finding_id in recommendation.get("finding_ids", []):
            if finding_id not in id_sets.get("findings", set()):
                errors.append(f"recommendation_finding_missing:{rid}:{finding_id}")
        if contract_version == "2.3" and recommendation.get("priority") not in {"now", "next", "later"}:
            errors.append(f"recommendation_priority_invalid:{rid}:{recommendation.get('priority')}")

    experiments = data.get("experiments", [])
    if contract_version in {"2.1", "2.2", "2.3"} and data.get("route") in {"same_author_content", "account_content_performance"} and data.get("recommendations") and not experiments:
        errors.append("experiments_required_for_editorial_route")
    experiment_ids: set[str] = set()
    for experiment in experiments:
        experiment_id = str(experiment.get("id") or "")
        if not experiment_id:
            errors.append("experiment_id_missing")
        elif experiment_id in experiment_ids or experiment_id in all_ids:
            errors.append(f"experiment_id_duplicate:{experiment_id}")
        experiment_ids.add(experiment_id)
        for key in (
            "title", "question", "hypothesis", "comparison_design", "changed_variable", "baseline",
            "primary_metric", "guardrail_metrics", "measurement_window", "minimum_sample", "decision_rule",
            "required_data", "confounders", "stop_condition", "linked_finding_ids",
        ):
            if experiment.get(key) in (None, "", []):
                errors.append(f"experiment_incomplete:{experiment_id or '<missing>'}:{key}")
        for key in ("guardrail_metrics", "required_data", "confounders", "linked_finding_ids"):
            if key in experiment and not isinstance(experiment.get(key), list):
                errors.append(f"experiment_list_invalid:{experiment_id}:{key}")
        for finding_id in experiment.get("linked_finding_ids", []):
            if finding_id not in id_sets.get("findings", set()):
                errors.append(f"experiment_finding_missing:{experiment_id}:{finding_id}")

    if contract_version in {"2.2", "2.3"}:
        checklist = data.get("analysis_checklist")
        if not isinstance(checklist, list) or not checklist:
            errors.append("analysis_checklist_empty")
            checklist = []
        checklist_ids: set[str] = set()
        for item in checklist:
            checklist_id = str(item.get("id") or "")
            if not checklist_id or checklist_id in checklist_ids:
                errors.append(f"analysis_checklist_id_invalid:{checklist_id or '<missing>'}")
            checklist_ids.add(checklist_id)
            for key in ("question", "status", "evidence_ids", "finding_ids", "note"):
                if key not in item or item.get(key) in (None, ""):
                    errors.append(f"analysis_checklist_incomplete:{checklist_id or '<missing>'}:{key}")
            status = item.get("status")
            if status not in VALID_CHECKLIST_STATUS:
                errors.append(f"analysis_checklist_status_invalid:{checklist_id}:{status}")
            if not isinstance(item.get("evidence_ids"), list) or not isinstance(item.get("finding_ids"), list):
                errors.append(f"analysis_checklist_links_invalid:{checklist_id}")
            if status == "answered" and (not item.get("evidence_ids") or not item.get("finding_ids")):
                errors.append(f"analysis_checklist_answer_unlinked:{checklist_id}")
            for evidence_id in item.get("evidence_ids", []):
                if evidence_id not in id_sets.get("evidence", set()):
                    errors.append(f"analysis_checklist_evidence_missing:{checklist_id}:{evidence_id}")
            for finding_id in item.get("finding_ids", []):
                if finding_id not in id_sets.get("findings", set()):
                    errors.append(f"analysis_checklist_finding_missing:{checklist_id}:{finding_id}")
        required_checklist = ROUTE_CHECKLISTS.get(str(data.get("route") or ""), set())
        for missing_id in sorted(required_checklist - checklist_ids):
            errors.append(f"analysis_checklist_route_item_missing:{missing_id}")

        visual_available = any(
            item.get("lane") == "visual_layout" and item.get("status") == "available"
            for item in data.get("evidence_coverage", [])
        )
        if visual_available and not any(
            (item.get("locator") or {}).get("type") == "image" and item.get("review_status") == "semantically_reviewed"
            for item in data.get("evidence", [])
        ):
            errors.append("visual_coverage_available_without_semantic_evidence")

    if depth == "deep":
        route = data.get("route")
        if route == "account_content_performance":
            minimums = {"findings": 6, "comparisons": 3, "analysis_sections": 4, "recommendations": 4, "evidence": 12}
        elif route == "mixed_corpus":
            minimums = {"findings": 5, "comparisons": 2, "analysis_sections": 4, "recommendations": 4, "evidence": 10}
        else:
            minimums = {"findings": 3, "comparisons": 2, "analysis_sections": 3, "recommendations": 3, "evidence": 6}
        for key, minimum in minimums.items():
            actual = len(data.get(key, []))
            if actual < minimum:
                errors.append(f"deep_minimum_not_met:{key}:{actual}<{minimum}")
    elif depth == "standard" and contract_version in {"2.2", "2.3"}:
        route = str(data.get("route") or "")
        minimums_by_route = {
            "same_author_content": {"findings": 5, "comparisons": 2, "analysis_sections": 3, "recommendations": 3, "evidence": 8},
            "method_corpus": {"findings": 5, "comparisons": 2, "analysis_sections": 3, "recommendations": 2, "evidence": 8},
            "mixed_corpus": {"findings": 5, "comparisons": 2, "analysis_sections": 4, "recommendations": 4, "evidence": 10},
            "novel_route": {"findings": 3, "comparisons": 1, "analysis_sections": 2, "recommendations": 2, "evidence": 5},
        }
        for key, minimum in minimums_by_route.get(route, {}).items():
            actual = len(data.get(key, []))
            if actual < minimum:
                errors.append(f"standard_minimum_not_met:{key}:{actual}<{minimum}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {key: len(data.get(key, [])) for key in ("executive_summary", "evidence", "findings", "comparisons", "analysis_sections", "recommendations", "experiments", "evidence_coverage", "limitations", "unanswered_questions")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a lossless Data Lens deep_analysis.json artifact.")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    result = validate_analysis(load_json(args.analysis))
    if args.json_report:
        write_json(args.json_report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
