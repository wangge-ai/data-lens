from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


VALID_RETENTION_STATUSES = {"retained", "strengthened", "superseded"}


def baseline_finding_items(snapshot: Any) -> list[dict[str, str]]:
    if not isinstance(snapshot, dict):
        return []
    rows = snapshot.get("retained_findings")
    if not isinstance(rows, list):
        return []
    return [
        {"baseline_finding_id": f"E0-R{index:03d}", "text": text.strip()}
        for index, value in enumerate(rows, start=1)
        if isinstance(value, str) and (text := value.strip())
    ]


def assess_baseline_preservation(
    report: Any,
    baseline_snapshot: Any,
) -> dict[str, Any]:
    required = baseline_finding_items(baseline_snapshot)
    required_ids = {item["baseline_finding_id"] for item in required}
    required_text = {
        item["baseline_finding_id"]: item["text"] for item in required
    }
    errors: list[str] = []

    if not isinstance(report, dict):
        report = {}
        errors.append("report must be an object")
    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []
    report_finding_ids = {
        str(item.get("id") or "").strip()
        for item in findings
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    evidence = report.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    report_evidence_ids = {
        str(item.get("id") or "").strip()
        for item in evidence
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }

    mappings = report.get("baseline_retention")
    if not isinstance(mappings, list):
        mappings = []
        if required:
            errors.append("baseline_retention must map every retained E0 finding")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(mappings):
        if not isinstance(row, dict):
            errors.append(f"baseline_retention[{index}] must be an object")
            continue
        finding_id = str(row.get("baseline_finding_id") or "").strip()
        status = str(row.get("status") or "").strip()
        rationale = str(row.get("rationale") or "").strip()
        linked_findings = row.get("report_finding_ids")
        linked_evidence = row.get("evidence_ids")
        if not isinstance(linked_findings, list):
            linked_findings = []
            errors.append(
                f"baseline_retention[{finding_id or index}].report_finding_ids must be an array"
            )
        if not isinstance(linked_evidence, list):
            linked_evidence = []
            errors.append(
                f"baseline_retention[{finding_id or index}].evidence_ids must be an array"
            )
        linked_findings = [
            value.strip() for value in linked_findings
            if isinstance(value, str) and value.strip()
        ]
        linked_evidence = [
            value.strip() for value in linked_evidence
            if isinstance(value, str) and value.strip()
        ]
        if not finding_id:
            errors.append(f"baseline_retention[{index}].baseline_finding_id is required")
        elif finding_id in seen:
            errors.append(f"baseline_retention duplicates {finding_id}")
        elif finding_id not in required_ids:
            errors.append(f"baseline_retention references unknown finding {finding_id}")
        seen.add(finding_id)
        if status not in VALID_RETENTION_STATUSES:
            errors.append(f"baseline_retention[{finding_id or index}].status is invalid")
        if not rationale:
            errors.append(f"baseline_retention[{finding_id or index}].rationale is required")
        if not linked_findings:
            errors.append(
                f"baseline_retention[{finding_id or index}] must point to a retained or replacement report finding"
            )
        for linked_id in linked_findings:
            if linked_id not in report_finding_ids:
                errors.append(
                    f"baseline_retention[{finding_id or index}] references unknown report finding {linked_id}"
                )
        if status == "superseded" and not linked_evidence:
            errors.append(
                f"baseline_retention[{finding_id or index}] supersession requires evidence_ids"
            )
        for evidence_id in linked_evidence:
            if evidence_id not in report_evidence_ids:
                errors.append(
                    f"baseline_retention[{finding_id or index}] references unknown evidence {evidence_id}"
                )
        normalized.append({
            "baseline_finding_id": finding_id,
            "baseline_text": required_text.get(finding_id),
            "status": status,
            "report_finding_ids": linked_findings,
            "evidence_ids": linked_evidence,
            "rationale": rationale,
        })

    missing = sorted(required_ids - seen)
    if missing:
        errors.append("baseline_retention is missing:" + ",".join(missing))
    return {
        "complete": not errors,
        "required_count": len(required),
        "mapped_count": len(required_ids & seen),
        "missing_ids": missing,
        "errors": errors,
        "mappings": normalized,
    }


def build_final_review(
    baseline_snapshot: Any,
    report: Any | None = None,
    operational_analysis: Any | None = None,
    single_first_stop_point: bool = False,
) -> dict[str, Any]:
    """Build one advisory final-edit brief from the existing E0 snapshot.

    This does not create a second baseline, rerun analysis, or decide release.
    It exposes already-computed coverage claims beside the existing retention
    mapping so a host can make one reader-facing edit without transcribing
    counts from prose or memory.
    """
    required = baseline_finding_items(baseline_snapshot)
    preservation = (
        assess_baseline_preservation(report, baseline_snapshot)
        if report is not None
        else {
            "complete": False if required else True,
            "required_count": len(required),
            "mapped_count": 0,
            "missing_ids": [item["baseline_finding_id"] for item in required],
            "errors": [],
            "mappings": [],
        }
    )
    coverage = []
    if isinstance(operational_analysis, dict):
        rows = operational_analysis.get("coverage_summary")
        if isinstance(rows, list):
            coverage = [row for row in rows if isinstance(row, dict)]
    return {
        "artifact_type": "data-lens-reader-final-review/1.0",
        "review_mode": "single_advisory_edit_not_a_gate",
        "required_findings": required,
        "baseline_preservation": preservation,
        "deterministic_coverage_claims": coverage,
        "instructions": [
            "Compare the draft once with required_findings and restore every high-value item that is missing, unless evidence has explicitly superseded it.",
            "Copy reader-facing coverage counts only from deterministic_coverage_claims; if the needed analysis unit is absent, omit the count or add it to the source facts before drafting.",
            "Keep the retention mapping and this review internal; remove E0/E1, evaluation, routing, contract, ledger, and gate language from the reader report.",
            (
                "Keep exactly one first stop point and move dependent actions to a later stage."
                if single_first_stop_point
                else "Preserve the user's requested action ordering and stopping conditions."
            ),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare one advisory reader-finalization pass from the existing E0 retention table."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--operational-analysis", type=Path)
    parser.add_argument("--single-first-stop-point", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [
        args.baseline,
        *([args.report] if args.report else []),
        *([args.operational_analysis] if args.operational_analysis else []),
    ]
    guard_cli_output(parser, args.output, sources)
    payload = build_final_review(
        load_json(args.baseline),
        load_json(args.report) if args.report else None,
        load_json(args.operational_analysis) if args.operational_analysis else None,
        args.single_first_stop_point,
    )
    write_json(args.output, payload)
    print(json.dumps({
        "review_mode": payload["review_mode"],
        "required_findings": len(payload["required_findings"]),
        "coverage_claims": len(payload["deterministic_coverage_claims"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
