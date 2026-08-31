from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

from _common import load_json, write_json


FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!")


def validate(workbook_path: Path, analysis_path: Path, html_path: Path, viewport_qa_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for path, label in ((workbook_path, "workbook"), (analysis_path, "analysis"), (html_path, "html"), (viewport_qa_path, "viewport_qa")):
        if not path.is_file():
            errors.append(f"missing_{label}:{path}")
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    analysis = load_json(analysis_path)
    html_text = html_path.read_text(encoding="utf-8-sig")
    if not re.search(r'<meta[^>]+name=["\']viewport["\']', html_text, re.I):
        errors.append("html_missing_viewport_meta")
    if not re.search(r"overflow-x\s*:\s*(?:auto|scroll)", html_text, re.I):
        errors.append("html_missing_horizontal_table_overflow_rule")
    for platform_name in (analysis.get("platform_dimension") or {}).get("platforms", []):
        if html.escape(str(platform_name), quote=True) not in html_text and str(platform_name) not in html_text:
            errors.append(f"html_missing_platform:{platform_name}")

    viewport = load_json(viewport_qa_path)
    checked_widths = {int(item.get("width")) for item in viewport.get("viewports", []) if item.get("width")}
    if not any(width <= 400 for width in checked_widths):
        errors.append("viewport_qa_missing_mobile_width")
    if not any(width >= 1200 for width in checked_widths):
        errors.append("viewport_qa_missing_desktop_width")
    for item in viewport.get("viewports", []):
        if item.get("body_horizontal_overflow") is True:
            errors.append(f"viewport_body_overflow:{item.get('width')}")
        if item.get("platform_controls_clipped") is True:
            errors.append(f"viewport_platform_controls_clipped:{item.get('width')}")

    try:
        from openpyxl import load_workbook
        from openpyxl.utils.cell import range_boundaries
    except ImportError:
        errors.append("openpyxl_required_for_operational_workbook_validation")
        return {"valid": False, "errors": errors, "warnings": warnings}

    workbook_formula = load_workbook(workbook_path, data_only=False, read_only=False)
    workbook_values = load_workbook(workbook_path, data_only=True, read_only=False)
    table_count = 0
    platform_table_count = 0
    formula_count = 0
    formula_error_cells: list[str] = []
    for sheet in workbook_formula.worksheets:
        table_count += len(sheet.tables)
        for table in sheet.tables.values():
            min_col, min_row, max_col, _ = range_boundaries(table.ref)
            headers = [str(sheet.cell(min_row, col).value or "").strip().lower() for col in range(min_col, max_col + 1)]
            if any(value in {"平台", "platform"} for value in headers):
                platform_table_count += 1
        value_sheet = workbook_values[sheet.title]
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    formula_count += 1
                    if any(token in value.upper() for token in FORMULA_ERRORS):
                        formula_error_cells.append(f"{sheet.title}!{cell.coordinate}")
                    cached = value_sheet[cell.coordinate].value
                    if isinstance(cached, str) and cached.upper() in FORMULA_ERRORS:
                        formula_error_cells.append(f"{sheet.title}!{cell.coordinate}")
                elif isinstance(value, str) and value.upper() in FORMULA_ERRORS:
                    formula_error_cells.append(f"{sheet.title}!{cell.coordinate}")
    if table_count == 0:
        errors.append("workbook_missing_excel_tables_or_dynamic_ranges")
    if (analysis.get("platform_dimension") or {}).get("platforms") and platform_table_count == 0:
        errors.append("workbook_tables_missing_platform_dimension")
    if formula_error_cells:
        errors.append("workbook_formula_errors:" + ",".join(sorted(set(formula_error_cells))[:20]))

    validation_sheet_name = "_corpus_lens_validation"
    if validation_sheet_name not in workbook_values.sheetnames:
        errors.append("workbook_missing_total_reconciliation_sheet")
    else:
        sheet = workbook_values[validation_sheet_name]
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            errors.append("workbook_reconciliation_empty")
        else:
            header = [str(value or "").strip().lower() for value in rows[0]]
            status_index = header.index("status") if "status" in header else -1
            if status_index < 0:
                errors.append("workbook_reconciliation_missing_status")
            else:
                statuses = [str(row[status_index] or "").strip().upper() for row in rows[1:] if len(row) > status_index]
                if not statuses or any(status != "PASS" for status in statuses):
                    errors.append("workbook_total_reconciliation_failed")
        if sheet.sheet_state != "hidden":
            warnings.append("workbook_reconciliation_sheet_should_be_hidden")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "excel_tables": table_count,
            "platform_tables": platform_table_count,
            "formulas_scanned": formula_count,
            "viewports_checked": sorted(checked_widths),
            "platforms_expected": (analysis.get("platform_dimension") or {}).get("platforms", []),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate workbook-first and responsive HTML outputs for repeated operational tables.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--viewport-qa", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.workbook, args.analysis, args.html, args.viewport_qa)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
