from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


LEGACY_LEDGER_VERSION = "data-lens-incremental-discovery-ledger/0.1"
LEDGER_VERSION = "data-lens-incremental-discovery-ledger/0.2"
LEGACY_REVIEW_VERSION = "data-lens-incremental-discovery-reviews/0.1"
REVIEW_VERSION = "data-lens-incremental-discovery-reviews/0.2"
LEGACY_EXPERIMENT_RESULT_VERSION = "data-lens-hypothesis-experiment-result/0.1"
EXPERIMENT_RESULT_VERSION = "data-lens-hypothesis-experiment-result/0.2"
ASSESSMENT_VERSION = "data-lens-incremental-discovery-assessment/0.3"
STRUCTURE_STATUSES = {"distinct", "same", "unresolved"}
PREDICTION_STATUSES = {"divergent", "same", "untestable"}
HOLDOUT_STATUSES = {"supports_e1", "supports_e0", "mixed", "not_tested"}
DECISION_STATUSES = {"changes", "refines", "no_change"}
MECHANISM_TEST_STATUSES = {"direct", "partial", "tangential", "unsafe"}
NOVELTY_STATUSES = {"new_to_e0", "already_in_e0", "overlaps_e0", "unresolved"}


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_list(value: Any, field: str, errors: list[str], *, required: bool = True) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    output = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(output) != len(value):
        errors.append(f"{field} must contain non-empty strings")
    if required and not output:
        errors.append(f"{field} must not be empty")
    return output


def assess_incremental_discovery(ledger: Any, review_payload: Any) -> dict[str, Any]:
    if not isinstance(ledger, dict) or ledger.get("contract_version") not in {
        LEGACY_LEDGER_VERSION,
        LEDGER_VERSION,
    }:
        raise ValueError("unsupported incremental discovery ledger")
    if not isinstance(review_payload, dict) or review_payload.get("contract_version") not in {
        LEGACY_REVIEW_VERSION,
        REVIEW_VERSION,
    }:
        raise ValueError("unsupported incremental discovery review contract")
    measured_review = review_payload.get("contract_version") == REVIEW_VERSION
    decision_question = str(ledger.get("decision_question") or "").strip()
    if str(review_payload.get("decision_question") or "").strip() != decision_question:
        raise ValueError("review decision_question must exactly match the candidate ledger")
    rows = review_payload.get("reviews")
    if not isinstance(rows, list):
        raise ValueError("reviews must be an array")

    experiment_results: dict[str, dict[str, Any]] = {}
    if measured_review:
        raw_results = review_payload.get("experiment_results")
        if not isinstance(raw_results, list):
            raise ValueError("experiment_results must be an array for review contract 0.2")
        duplicate_experiment_ids: set[str] = set()
        for result in raw_results:
            if not isinstance(result, dict):
                raise ValueError("each experiment result must be an object")
            experiment_id = _text(result, "experiment_id")
            if not experiment_id:
                raise ValueError("each experiment result requires experiment_id")
            if experiment_id in experiment_results:
                duplicate_experiment_ids.add(experiment_id)
            experiment_results[experiment_id] = result
        if duplicate_experiment_ids:
            raise ValueError(f"duplicate experiment results:{','.join(sorted(duplicate_experiment_ids))}")

    candidates = {str(item.get("candidate_id") or ""): item for item in ledger.get("candidates", [])}
    candidate_generation_pass = str(
        ledger.get("search", {}).get("candidate_generation_pass") or ""
    ).strip()
    reviews: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each review must be an object")
        candidate_id = _text(row, "candidate_id")
        if candidate_id in reviews:
            duplicate_ids.add(candidate_id)
        reviews[candidate_id] = row
    if duplicate_ids:
        raise ValueError(f"duplicate candidate reviews:{','.join(sorted(duplicate_ids))}")
    unknown_ids = sorted(set(reviews) - set(candidates))
    if unknown_ids:
        raise ValueError(f"reviews reference unknown candidates:{','.join(unknown_ids)}")

    assessed: list[dict[str, Any]] = []
    missing_reviews: list[str] = []
    for candidate_id, compiled in candidates.items():
        if not compiled.get("eligible_for_review"):
            assessed.append({
                "candidate_id": candidate_id,
                "outcome": "rejected_mechanical",
                "review_valid": False,
                "review_errors": [],
                "reason": "candidate did not pass structural, evidence, or direct-test checks",
            })
            continue
        row = reviews.get(candidate_id)
        if row is None:
            missing_reviews.append(candidate_id)
            assessed.append({
                "candidate_id": candidate_id,
                "outcome": "pending_review",
                "review_valid": False,
                "review_errors": ["review missing"],
                "reason": None,
            })
            continue
        errors: list[str] = []
        reviewer_pass = _text(row, "reviewer_pass")
        rationale = _text(row, "rationale")
        if not reviewer_pass:
            errors.append("reviewer_pass is required")
        elif reviewer_pass == candidate_generation_pass:
            errors.append("reviewer_pass must differ from candidate_generation_pass")
        if not rationale:
            errors.append("rationale is required")
        structure_status = _text(row, "structure_status")
        prediction_status = _text(row, "prediction_status")
        novelty_status = _text(row, "novelty_status")
        mechanism_test_status = _text(row, "mechanism_test_status")
        holdout_status = "not_tested" if measured_review else _text(row, "holdout_status")
        decision_status = _text(row, "decision_status")
        if structure_status not in STRUCTURE_STATUSES:
            errors.append("structure_status is invalid")
        if prediction_status not in PREDICTION_STATUSES:
            errors.append("prediction_status is invalid")
        if novelty_status not in NOVELTY_STATUSES:
            errors.append("novelty_status is invalid")
        if mechanism_test_status not in MECHANISM_TEST_STATUSES:
            errors.append("mechanism_test_status is invalid")
        experiment_result_id = ""
        experiment_result: dict[str, Any] | None = None
        if measured_review:
            if "holdout_status" in row:
                errors.append("review contract 0.2 derives holdout_status from Python; it must not be supplied")
            experiment_result_id = _text(row, "experiment_result_id")
            if experiment_result_id:
                experiment_result = experiment_results.get(experiment_result_id)
                if experiment_result is None:
                    errors.append("experiment_result_id does not reference a supplied experiment result")
                else:
                    result_version = experiment_result.get("contract_version")
                    if result_version != EXPERIMENT_RESULT_VERSION:
                        if result_version == LEGACY_EXPERIMENT_RESULT_VERSION:
                            errors.append("legacy experiment result lacks a frozen executable binding")
                        else:
                            errors.append("experiment result contract is unsupported")
                    if _text(experiment_result, "decision_question") != decision_question:
                        errors.append("experiment result decision_question differs from the candidate ledger")
                    if _text(experiment_result, "mode") != "hypothesis_comparison":
                        errors.append("increment review requires a hypothesis_comparison experiment result")
                    if _text(experiment_result, "candidate_id") != candidate_id:
                        errors.append("experiment result candidate_id differs from the reviewed candidate")
                    candidate_mechanism = compiled.get("candidate", {}).get("core_mechanism")
                    if _normalize(experiment_result.get("target_mechanism")) != _normalize(candidate_mechanism):
                        errors.append("experiment result target differs from the candidate core mechanism")
                    candidate_test = compiled.get("candidate", {}).get("discriminating_test", {})
                    test_binding = experiment_result.get("test_binding", {})
                    for result_field, candidate_field in (
                        ("changed_variable", "changed_variable"),
                        ("measurement_window", "measurement_window"),
                        ("distinguishing_observation", "distinguishing_observation"),
                    ):
                        if _normalize(test_binding.get(result_field)) != _normalize(candidate_test.get(candidate_field)):
                            errors.append(f"experiment result {result_field} differs from the frozen candidate test")
                    hypothesis_rows = experiment_result.get("hypotheses")
                    hypothesis_text = {
                        _text(item, "hypothesis_id"): _text(item, "statement")
                        for item in hypothesis_rows
                        if isinstance(item, dict)
                    } if isinstance(hypothesis_rows, list) else {}
                    baseline_hypothesis_id = _text(experiment_result, "baseline_hypothesis_id")
                    candidate_hypothesis_id = _text(experiment_result, "candidate_hypothesis_id")
                    if _normalize(hypothesis_text.get(baseline_hypothesis_id)) != _normalize(candidate_test.get("e0_prediction")):
                        errors.append("experiment E0 prediction differs from the frozen candidate prediction")
                    if candidate_hypothesis_id != candidate_id:
                        errors.append("experiment candidate hypothesis ID differs from candidate_id")
                    if _normalize(hypothesis_text.get(candidate_hypothesis_id)) != _normalize(candidate_test.get("e1_prediction")):
                        errors.append("experiment E1 prediction differs from the frozen candidate prediction")
                    if experiment_result.get("direct_binding", {}).get("valid") is not True:
                        errors.append("experiment result did not pass direct mechanism binding")
                    if experiment_result.get("execution_status") != "completed":
                        errors.append("experiment result was not completed")
                    frozen_execution = candidate_test.get("execution_binding")
                    actual_execution = experiment_result.get("execution_binding")
                    if not isinstance(frozen_execution, dict) or not isinstance(actual_execution, dict):
                        errors.append("experiment result lacks the frozen executable test binding")
                    else:
                        if _normalize(actual_execution.get("mechanism_variable")) != _normalize(
                            frozen_execution.get("mechanism_variable")
                        ):
                            errors.append("experiment mechanism_variable differs from the frozen candidate test")
                        actual_data_refs = _text_list(
                            actual_execution.get("data_evidence_refs"),
                            "experiment execution_binding.data_evidence_refs",
                            errors,
                        )
                        frozen_data_refs = _text_list(
                            frozen_execution.get("data_evidence_refs"),
                            "frozen execution_binding.data_evidence_refs",
                            errors,
                        )
                        if sorted(actual_data_refs) != sorted(frozen_data_refs):
                            errors.append("experiment data evidence differs from the frozen candidate test")
                        if _text(actual_execution, "required_granularity") != _text(
                            frozen_execution, "required_granularity"
                        ):
                            errors.append("experiment required_granularity differs from the frozen candidate test")
                        for binding_field in ("evaluation_window", "measurement"):
                            if _canonical(actual_execution.get(binding_field)) != _canonical(
                                frozen_execution.get(binding_field)
                            ):
                                errors.append(
                                    f"experiment {binding_field} differs from the frozen candidate test"
                                )
                        actual_predictions = actual_execution.get("hypothesis_predictions")
                        if not isinstance(actual_predictions, dict):
                            errors.append("experiment hypothesis_predictions must be an object")
                            actual_predictions = {}
                        if _canonical(actual_predictions.get(baseline_hypothesis_id)) != _canonical(
                            frozen_execution.get("e0_predicate")
                        ):
                            errors.append("experiment E0 predicate differs from the frozen candidate test")
                        if _canonical(actual_predictions.get(candidate_hypothesis_id)) != _canonical(
                            frozen_execution.get("e1_predicate")
                        ):
                            errors.append("experiment E1 predicate differs from the frozen candidate test")
                    derived_direction = _text(experiment_result, "evidence_direction")
                    if derived_direction not in HOLDOUT_STATUSES - {"not_tested"}:
                        errors.append("experiment result has no usable evidence direction")
                    else:
                        holdout_status = derived_direction
        if holdout_status not in HOLDOUT_STATUSES:
            errors.append("holdout_status is invalid")
        if decision_status not in DECISION_STATUSES:
            errors.append("decision_status is invalid")
        evidence_refs = _text_list(
            row.get("review_evidence_refs"),
            "review_evidence_refs",
            errors,
            required=holdout_status != "not_tested",
        )
        holdout_refs = set(compiled.get("candidate", {}).get("holdout_evidence_refs") or [])
        outside_holdout = sorted(set(evidence_refs) - holdout_refs)
        if outside_holdout:
            errors.append(f"review evidence must come from declared holdout evidence:{','.join(outside_holdout)}")
        if holdout_status == "not_tested" and evidence_refs:
            errors.append("not_tested review must not cite holdout evidence")
        if experiment_result is not None and isinstance(experiment_result.get("execution_binding"), dict):
            experiment_evidence_refs = _text_list(
                experiment_result["execution_binding"].get("data_evidence_refs"),
                "experiment execution_binding.data_evidence_refs",
                errors,
            )
            if sorted(evidence_refs) != sorted(experiment_evidence_refs):
                errors.append("review evidence differs from the evidence used by the experiment")

        candidate = compiled.get("candidate", {})
        baseline_snapshot = ledger.get("baseline", {}).get("snapshot", {})
        external_baseline = baseline_snapshot.get("capture_mode") == "external_raw_baseline"
        external_texts = [
            baseline_snapshot.get("core_problem"),
            baseline_snapshot.get("mechanism"),
            *(baseline_snapshot.get("retained_findings") or []),
        ]
        external_predictions = baseline_snapshot.get("predictions") or []
        exact_claim_overlap = bool(
            external_baseline
            and _normalize(candidate.get("claim"))
            and _normalize(candidate.get("claim")) in {_normalize(item) for item in external_texts}
        )
        exact_prediction_overlap = bool(
            external_baseline
            and _normalize(candidate.get("discriminating_test", {}).get("e1_prediction"))
            and _normalize(candidate.get("discriminating_test", {}).get("e1_prediction"))
            in {_normalize(item) for item in external_predictions}
        )

        legacy_would_claim_increment = bool(
            not measured_review
            and not errors
            and structure_status == "distinct"
            and prediction_status == "divergent"
            and novelty_status == "new_to_e0"
            and mechanism_test_status == "direct"
            and decision_status != "no_change"
            and holdout_status != "supports_e0"
        )
        if legacy_would_claim_increment:
            errors.append("legacy review cannot establish analysis increment without a measured direct experiment")

        if errors:
            outcome = "invalid_review"
        elif exact_claim_overlap or exact_prediction_overlap:
            outcome = "no_increment"
        elif (
            structure_status != "distinct"
            or prediction_status != "divergent"
            or novelty_status != "new_to_e0"
            or mechanism_test_status != "direct"
            or decision_status == "no_change"
        ):
            outcome = "no_increment"
        elif holdout_status == "supports_e0":
            outcome = "no_increment"
        elif holdout_status == "supports_e1":
            outcome = "validated_increment"
        else:
            outcome = "testable_increment"
        assessed.append({
            "candidate_id": candidate_id,
            "outcome": outcome,
            "review_valid": not errors,
            "review_errors": errors,
            "external_baseline_exact_overlap": {
                "claim": exact_claim_overlap,
                "prediction": exact_prediction_overlap,
            },
            "review": {
                "reviewer_pass": reviewer_pass,
                "structure_status": structure_status,
                "prediction_status": prediction_status,
                "novelty_status": novelty_status,
                "mechanism_test_status": mechanism_test_status,
                "holdout_status": holdout_status,
                "decision_status": decision_status,
                "experiment_result_id": experiment_result_id if measured_review else None,
                "review_evidence_refs": evidence_refs,
                "rationale": rationale,
            },
        })

    validated = [item["candidate_id"] for item in assessed if item["outcome"] == "validated_increment"]
    testable = [item["candidate_id"] for item in assessed if item["outcome"] == "testable_increment"]
    comparison_baseline_mode = str(
        ledger.get("baseline", {}).get("snapshot", {}).get("capture_mode") or ""
    )
    comparison = ledger.get("comparison") or {}
    external_coverage_invalid = bool(
        comparison.get("scope") == "strict_paired_external_raw"
        and (comparison.get("semantic_coverage_review") or {}).get("valid") is not True
    )
    if not ledger.get("baseline", {}).get("adequate_for_augmentation") or external_coverage_invalid:
        overall = "review_incomplete"
    elif missing_reviews or any(item["outcome"] == "invalid_review" for item in assessed):
        overall = "review_incomplete"
    elif validated:
        overall = "validated_increment"
    elif testable:
        overall = "testable_increment"
    else:
        overall = "no_increment"
    reader_notice = (
        "本轮没有分析增量。"
        if overall == "no_increment"
        else "本轮没有分析增量：增量评审未完成或无效。"
        if overall == "review_incomplete"
        else "本轮只产生了可检验的新解释，尚不能宣称分析增量。"
        if overall == "testable_increment"
        else None
    )
    final_report_mode = (
        "e0_plus_validated_increment"
        if overall == "validated_increment"
        else "e0_plus_labeled_unvalidated_hypothesis"
        if overall == "testable_increment"
        else "e0_only"
    )
    return {
        "contract_version": ASSESSMENT_VERSION,
        "decision_question": decision_question,
        "baseline_snapshot": ledger.get("baseline", {}).get("snapshot", {}),
        "recommended_mode": ledger.get("search", {}).get("recommended_mode"),
        "candidate_assessments": assessed,
        "summary": {
            "overall_result": overall,
            "validated_increment_ids": validated,
            "testable_increment_ids": testable,
            "missing_review_ids": missing_reviews,
            "analysis_increment_claimed": overall == "validated_increment",
            "relative_to_raw_model_claimed": (
                overall == "validated_increment"
                and comparison_baseline_mode == "external_raw_baseline"
            ),
            "comparison_baseline_mode": comparison_baseline_mode,
            "reader_notice": reader_notice,
            "final_report_mode": final_report_mode,
        },
        "next_step": (
            "adapt surviving candidates into the existing deep-finding pipeline"
            if overall in {"validated_increment", "testable_increment"}
            else "preserve E0 and continue with evidence calibration only"
            if overall == "no_increment"
            else "preserve E0; do not synthesize E1; repair the review before any increment claim"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess incremental candidates in a separate review pass using declared holdout evidence."
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.ledger, args.reviews])
    result = assess_incremental_discovery(load_json(args.ledger), load_json(args.reviews))
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "summary": result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
