from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from compile_deep_findings import adapt_deep_evidence
from compile_incremental_discovery import compile_baseline


BASELINE_VERSION = "data-lens-incremental-discovery-baseline/0.1"
BRIEF_VERSION = "data-lens-incremental-discovery-brief/0.1"


def prepare_incremental_discovery(
    payload: Any,
    evidence_payload: Any,
    evidence_base_dir: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("contract_version") != BASELINE_VERSION:
        raise ValueError("unsupported incremental discovery baseline contract")
    decision_question = str(payload.get("decision_question") or "").strip()
    if not decision_question:
        raise ValueError("decision_question is required and must preserve the user's original request")

    evidence = adapt_deep_evidence(evidence_payload, evidence_base_dir)
    baseline = compile_baseline(payload.get("native_first_pass"), evidence)
    adequate = baseline["adequate_for_augmentation"]
    missing = [name for name, present in baseline.get("adequacy", {}).items() if not present]
    recommended_mode = "adversarial_augmentation" if adequate else "full_discovery"
    return {
        "contract_version": BRIEF_VERSION,
        "decision_question": decision_question,
        "baseline": baseline,
        "recommended_mode": recommended_mode,
        "missing_baseline_capabilities": missing,
        "generation_brief": {
            "max_review_candidates": 2 if adequate else 0,
            "objective": (
                "challenge E0 with counterevidence and structurally different predictions; do not rerun full discovery"
                if adequate
                else "complete the ordinary first-pass analysis before attempting incremental candidates"
            ),
            "allowed_actions": (
                ["counterexample_search", "assumption_reversal", "structural_reframing", "divergent_prediction"]
                if adequate
                else ["complete_problem", "complete_mechanism", "add_competing_explanation", "add_prediction", "complete_decision"]
            ),
            "forbidden_actions": [
                "replace or delete retained E0 findings",
                "treat longer wording as analysis increment",
                "read holdout evidence before candidate predictions are frozen",
                "send more than the two highest-residual candidates to review",
            ],
        },
        "analysis_increment_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess E0 before candidate generation and select full discovery or adversarial augmentation."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--evidence-cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.baseline, args.evidence_cards])
    result = prepare_incremental_discovery(
        load_json(args.baseline),
        load_json(args.evidence_cards),
        args.evidence_cards.parent,
    )
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "recommended_mode": result["recommended_mode"],
        "missing_baseline_capabilities": result["missing_baseline_capabilities"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
