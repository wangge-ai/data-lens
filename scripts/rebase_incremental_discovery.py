from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from compile_deep_findings import adapt_deep_evidence
from compile_incremental_discovery import LEDGER_VERSION, compile_baseline


LEGACY_LEDGER_VERSION = "data-lens-incremental-discovery-ledger/0.1"
BASELINE_VERSION = "data-lens-incremental-discovery-baseline/0.1"


def _baseline_texts(snapshot: dict[str, Any]) -> set[str]:
    values: list[Any] = [
        snapshot.get("core_problem"),
        snapshot.get("mechanism"),
        snapshot.get("decision"),
        *(snapshot.get("competing_explanations") or []),
        *(snapshot.get("predictions") or []),
        *(snapshot.get("retained_findings") or []),
        *(snapshot.get("unresolved_observations") or []),
    ]
    return {str(value).strip() for value in values if str(value or "").strip()}


def _coverage_review(payload: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["external baseline coverage_review is required"]}
    reviewer_pass = str(payload.get("reviewer_pass") or "").strip()
    status = str(payload.get("status") or "").strip()
    material_findings = payload.get("material_findings")
    omitted = payload.get("omitted_material_findings")
    if not reviewer_pass:
        errors.append("coverage_review.reviewer_pass is required")
    if status != "complete":
        errors.append("coverage_review.status must be complete")
    if not isinstance(material_findings, list) or not material_findings:
        errors.append("coverage_review.material_findings must be a non-empty array")
        material_findings = []
    if not isinstance(omitted, list):
        errors.append("coverage_review.omitted_material_findings must be an array")
        omitted = []
    if omitted:
        errors.append("external raw final still has omitted material findings")
    baseline_texts = _baseline_texts(snapshot)
    for index, item in enumerate(material_findings):
        if not isinstance(item, dict):
            errors.append(f"coverage_review.material_findings[{index}] must be an object")
            continue
        locator = str(item.get("source_locator") or "").strip()
        baseline_text = str(item.get("baseline_text") or "").strip()
        if not locator or not baseline_text:
            errors.append(
                f"coverage_review.material_findings[{index}] requires source_locator and baseline_text"
            )
        elif baseline_text not in baseline_texts:
            errors.append(
                f"coverage_review.material_findings[{index}] baseline_text is absent from the external baseline"
            )
    return {
        "valid": not errors,
        "errors": errors,
        "reviewer_pass": reviewer_pass,
        "status": status,
        "material_finding_count": len(material_findings),
        "omitted_material_finding_count": len(omitted),
    }


def rebase_incremental_discovery(
    frozen_ledger: Any,
    external_baseline_payload: Any,
    evidence_payload: Any,
    evidence_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Attach a post-reveal raw-model baseline without regenerating E1 candidates."""

    if not isinstance(frozen_ledger, dict) or frozen_ledger.get("contract_version") not in {
        LEGACY_LEDGER_VERSION,
        LEDGER_VERSION,
    }:
        raise ValueError("unsupported frozen incremental discovery ledger")
    if (
        not isinstance(external_baseline_payload, dict)
        or external_baseline_payload.get("contract_version") != BASELINE_VERSION
    ):
        raise ValueError("unsupported external baseline contract")
    decision_question = str(frozen_ledger.get("decision_question") or "").strip()
    if str(external_baseline_payload.get("decision_question") or "").strip() != decision_question:
        raise ValueError("external baseline decision_question must exactly match the frozen ledger")

    evidence = adapt_deep_evidence(evidence_payload, evidence_base_dir)
    external_baseline = compile_baseline(
        external_baseline_payload.get("native_first_pass"), evidence
    )
    if external_baseline.get("normalized", {}).get("capture_mode") != "external_raw_baseline":
        raise ValueError("post-reveal comparison requires capture_mode=external_raw_baseline")
    coverage = _coverage_review(
        external_baseline_payload.get("coverage_review"),
        external_baseline.get("snapshot") or {},
    )

    rebased = deepcopy(frozen_ledger)
    frozen_candidates = deepcopy(frozen_ledger.get("candidates") or [])
    rebased["contract_version"] = LEDGER_VERSION
    rebased["generation_baseline"] = deepcopy(frozen_ledger.get("baseline") or {})
    rebased["baseline"] = external_baseline
    rebased["candidates"] = frozen_candidates
    rebased["evidence_index"] = evidence
    rebased["comparison"] = {
        "scope": "strict_paired_external_raw",
        "post_reveal": True,
        "candidate_generation_reused": True,
        "external_baseline_adequate": external_baseline.get("adequate_for_augmentation") is True,
        "semantic_coverage_review_required": True,
        "semantic_coverage_review": coverage,
    }
    rebased.setdefault("summary", {})["analysis_increment_claimed"] = False
    rebased["summary"]["comparison_baseline_mode"] = "external_raw_baseline"
    return rebased


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompare a frozen Skill candidate ledger against the real raw-model final result after reveal."
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--external-baseline", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(
        parser,
        args.output,
        [args.ledger, args.external_baseline, args.evidence_cards],
    )
    result = rebase_incremental_discovery(
        load_json(args.ledger),
        load_json(args.external_baseline),
        load_json(args.evidence_cards),
        args.evidence_cards.parent,
    )
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "candidate_count": len(result.get("candidates") or []),
                "comparison": result["comparison"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
