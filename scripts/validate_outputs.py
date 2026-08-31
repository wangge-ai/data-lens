from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json, write_json


def verify_record(record: dict[str, Any], label: str, errors: list[str]) -> None:
    path = Path(record.get("path", ""))
    if not path.is_file():
        errors.append(f"{label}_missing:{path}")
    elif record.get("sha256") != file_sha256(path):
        errors.append(f"{label}_hash_mismatch:{path.name}")


def validate(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    html_path = output_dir / "report.html"
    md_path = output_dir / "report.md"
    manifest_path = output_dir / "run_manifest.json"
    for path in (html_path, md_path, manifest_path):
        if not path.exists():
            errors.append(f"missing:{path.name}")
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    try:
        html_text = html_path.read_text(encoding="utf-8", errors="strict")
        md_text = md_path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return {"valid": False, "errors": [f"not_utf8:{exc}"], "warnings": warnings}

    for marker in ("����", "锟斤拷", "æŠ¥å‘Š", "ï¿½", "�"):
        if marker in html_text or marker in md_text:
            errors.append(f"mojibake_marker:{marker}")
    if '<meta charset="utf-8">' not in html_text.lower():
        errors.append("missing_utf8_meta")
    if 'data-data-lens-report="2"' not in html_text:
        errors.append("missing_v2_report_marker")
    for internal_text in (
        "方法、证据位置与运行记录", "实际读取的方法文件", "分析路线", "合同版本",
        "NOVEL_ROUTE", "mixed_corpus", "same_author_content", "account_content_performance", "method_corpus",
        "asset_role", "relation_type", "version_status", "source_path", "evidence_id", "run_context", "sha256",
    ):
        if internal_text in html_text:
            errors.append(f"reader_html_exposes_internal_trace:{internal_text}")
    if 'id="method-trace"' in html_text or 'class="evidence-index"' in html_text:
        errors.append("reader_html_exposes_audit_component")
    if re.search(r">\s*[EFRS]\d{2,}\s*<", html_text):
        errors.append("reader_html_exposes_internal_id")
    if re.search(r"[A-Za-z]:\\", html_text):
        errors.append("reader_html_exposes_local_path")
    for heading in ("报告任务识别", "资料审计", "生成状态"):
        if f">{heading}<" in html_text:
            errors.append(f"forbidden_process_heading:{heading}")
    if re.findall(r'(?:src|href)=["\']https?://', html_text, flags=re.I):
        warnings.append("external_asset_reference")

    manifest = load_json(manifest_path)
    for key in ("skill_name", "skill_version", "route", "report_depth", "analysis_artifact", "analysis_validation", "run_context", "method_loads", "deterministic_artifacts", "evidence_positions", "pipeline_steps", "outputs"):
        if key not in manifest or manifest.get(key) in (None, "", []):
            errors.append(f"manifest_missing:{key}")
    for key in ("analysis_artifact", "analysis_validation", "run_context"):
        if isinstance(manifest.get(key), dict):
            verify_record(manifest[key], key, errors)
    for item in manifest.get("method_loads", []):
        if not item.get("loaded"):
            errors.append(f"method_not_loaded:{item.get('path')}")
        verify_record(item, "method", errors)
    for item in manifest.get("deterministic_artifacts", []):
        if not item.get("loaded"):
            errors.append(f"artifact_not_loaded:{item.get('path')}")
        verify_record(item, "artifact", errors)
    for item in manifest.get("outputs", []):
        verify_record(item, "output", errors)

    if manifest.get("manifest_version") == "2.3":
        completion_status = manifest.get("completion_status")
        if completion_status not in {"preliminary", "final"}:
            errors.append(f"manifest_completion_status_invalid:{completion_status}")
        if f'class="completion-status status-{completion_status}"' not in html_text:
            errors.append("html_missing_completion_status")
        if completion_status == "preliminary" and "阶段性分析" not in html_text:
            errors.append("html_preliminary_not_disclosed")
        if completion_status == "final" and "完整分析" not in html_text:
            errors.append("html_final_not_disclosed")
        if 'class="overview-visuals"' not in html_text:
            errors.append("html_missing_compact_overview")

    content_checks: dict[str, int] = {}
    analysis_record = manifest.get("analysis_artifact", {})
    analysis_path = Path(analysis_record.get("path", ""))
    if analysis_path.is_file():
        analysis = load_json(analysis_path)
        if manifest.get("manifest_version") == "2.3" and manifest.get("completion_status") != analysis.get("completion_status"):
            errors.append("manifest_completion_status_mismatch")
        def require_visible(value: Any, label: str) -> None:
            if value in (None, ""):
                return
            text = str(value)
            if html.escape(text, quote=True) not in html_text:
                errors.append(f"html_content_omitted:{label}")
            if text not in md_text:
                errors.append(f"markdown_content_omitted:{label}")

        for collection in ("executive_summary", "findings", "comparisons", "analysis_sections", "recommendations", "experiments"):
            items = analysis.get(collection, [])
            content_checks[collection] = len(items)
            for item in items:
                title = str(item.get("title", ""))
                if title and html.escape(title, quote=True) not in html_text:
                    errors.append(f"html_content_omitted:{collection}:{item.get('id', title)}")
                if title and title not in md_text:
                    errors.append(f"markdown_content_omitted:{collection}:{item.get('id', title)}")
        for item in analysis.get("executive_summary", []):
            require_visible(item.get("summary"), f"executive_summary:{item.get('id')}:summary")
        for item in analysis.get("findings", []):
            for key in ("fact", "explanation"):
                require_visible(item.get(key), f"finding:{item.get('id')}:{key}")
            for key in ("counterexamples", "boundaries"):
                for index, value in enumerate(item.get(key, [])):
                    require_visible(value, f"finding:{item.get('id')}:{key}:{index}")
        for item in analysis.get("comparisons", []):
            for side_name in ("left", "right"):
                for key in ("label", "value", "body"):
                    require_visible(item.get(side_name, {}).get(key), f"comparison:{item.get('id')}:{side_name}:{key}")
            for key in ("interpretation", "counterexample", "boundary"):
                require_visible(item.get(key), f"comparison:{item.get('id')}:{key}")
        for section in analysis.get("analysis_sections", []):
            require_visible(section.get("summary"), f"section:{section.get('id')}:summary")
            for index, item in enumerate(section.get("items", [])):
                for key in ("title", "body", "boundary"):
                    require_visible(item.get(key), f"section:{section.get('id')}:item:{index}:{key}")
            for row_index, row in enumerate((section.get("table") or {}).get("rows", [])):
                for key, value in row.items():
                    require_visible(value, f"section:{section.get('id')}:table:{row_index}:{key}")
        for item in analysis.get("recommendations", []):
            for key in ("action", "rationale", "validation_metric", "timebox", "fallback"):
                require_visible(item.get(key), f"recommendation:{item.get('id')}:{key}")
            for index, value in enumerate(item.get("risks", [])):
                require_visible(value, f"recommendation:{item.get('id')}:risk:{index}")
        sampling = analysis.get("sampling") or {}
        for key in ("inclusion_rule", "eligible_count", "selected_count"):
            require_visible(sampling.get(key), f"sampling:{key}")
        for index, value in enumerate(sampling.get("bias_warnings", [])):
            require_visible(value, f"sampling:bias_warnings:{index}")
        for item in analysis.get("evidence_coverage", []):
            for key in ("items", "proves", "cannot_prove"):
                require_visible(item.get(key), f"coverage:{item.get('lane')}:{key}")
        for item in analysis.get("experiments", []):
            for key in (
                "question", "hypothesis", "comparison_design", "changed_variable", "baseline",
                "primary_metric", "measurement_window", "minimum_sample", "decision_rule", "stop_condition",
            ):
                require_visible(item.get(key), f"experiment:{item.get('id')}:{key}")
            for key in ("guardrail_metrics", "required_data", "confounders"):
                for index, value in enumerate(item.get(key, [])):
                    require_visible(value, f"experiment:{item.get('id')}:{key}:{index}")
        for collection in ("limitations", "unanswered_questions"):
            for index, value in enumerate(analysis.get(collection, [])):
                require_visible(value, f"{collection}:{index}")
        if len(manifest.get("evidence_positions", [])) != len(analysis.get("evidence", [])):
            errors.append("manifest_evidence_position_count_mismatch")

    return {"valid": not errors, "errors": errors, "warnings": warnings, "checks": {"html_bytes": html_path.stat().st_size, "markdown_bytes": md_path.stat().st_size, "manifest_outputs": len(manifest.get("outputs", [])), "content_counts": content_checks}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Data Lens V0.2 HTML, Markdown, run trace, and lossless content rendering.")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    result = validate(args.output_dir)
    if args.json_report:
        write_json(args.json_report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
