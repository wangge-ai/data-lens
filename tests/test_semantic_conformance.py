from __future__ import annotations

from copy import deepcopy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from assess_semantic_conformance import (  # noqa: E402
    assess_semantic_conformance,
    compare_semantic_conformance,
)


def expectations_fixture() -> dict:
    return {
        "contract_version": "data-lens-semantic-conformance-expectations/0.1",
        "cases": [
            {
                "case_id": "post-selection-causality",
                "dimension": "causal_calibration",
                "critical": True,
                "equals": {
                    "verdict": "unsupported",
                    "analysis_unit": "impression",
                    "minimum_direct_design": "randomized_experiment_or_valid_ope",
                },
                "includes": {
                    "reason_codes": [
                        "post_selection_bias",
                        "missing_propensity_or_randomization",
                    ]
                },
            },
            {
                "case_id": "anonymous-row-identity",
                "dimension": "unit_identity",
                "critical": True,
                "equals": {
                    "verdict": "unsupported",
                    "analysis_unit": "anonymous_context_row",
                },
                "includes": {"reason_codes": ["no_stable_entity_id"]},
            },
            {
                "case_id": "two-proportion-significance",
                "dimension": "statistical_calibration",
                "critical": True,
                "equals": {
                    "verdict": "not_significant",
                    "test": "two_sided_two_proportion_z",
                },
                "numeric": {
                    "p_value": {
                        "value": 0.4806396193806986,
                        "absolute_tolerance": 0.002,
                    }
                },
            },
            {
                "case_id": "mechanism-test-directness",
                "dimension": "mechanism_directness",
                "critical": True,
                "equals": {
                    "verdict": "tangential",
                    "required_changed_variable": "feedback_origin",
                },
                "includes": {
                    "reason_codes": [
                        "mechanism_variable_not_changed_or_observed"
                    ]
                },
            },
            {
                "case_id": "baseline-carry-forward",
                "dimension": "baseline_preservation",
                "critical": True,
                "equals": {"verdict": "incomplete"},
                "includes": {
                    "missing_baseline_finding_ids": ["E0-R002"]
                },
            },
        ],
    }


def responses_fixture(*, passed: bool = True) -> dict:
    passing = {
        "contract_version": "data-lens-semantic-conformance-responses/0.1",
        "host": "fixture-host",
        "model": "fixture-model",
        "run_id": "fixture-pass",
        "cases": [
            {
                "case_id": "post-selection-causality",
                "answers": {
                    "verdict": "unsupported",
                    "analysis_unit": "impression",
                    "reason_codes": [
                        "post_selection_bias",
                        "missing_propensity_or_randomization",
                    ],
                    "minimum_direct_design": "randomized_experiment_or_valid_ope",
                },
            },
            {
                "case_id": "anonymous-row-identity",
                "answers": {
                    "verdict": "unsupported",
                    "analysis_unit": "anonymous_context_row",
                    "reason_codes": ["no_stable_entity_id"],
                },
            },
            {
                "case_id": "two-proportion-significance",
                "answers": {
                    "verdict": "not_significant",
                    "test": "two_sided_two_proportion_z",
                    "p_value": 0.48064,
                },
            },
            {
                "case_id": "mechanism-test-directness",
                "answers": {
                    "verdict": "tangential",
                    "reason_codes": [
                        "mechanism_variable_not_changed_or_observed"
                    ],
                    "required_changed_variable": "feedback_origin",
                },
            },
            {
                "case_id": "baseline-carry-forward",
                "answers": {
                    "verdict": "incomplete",
                    "missing_baseline_finding_ids": ["E0-R002"],
                },
            },
        ],
    }
    if passed:
        return passing
    failing = deepcopy(passing)
    failing["run_id"] = "fixture-fail"
    failing["cases"] = [
        {
            "case_id": "post-selection-causality",
            "answers": {
                "verdict": "supported",
                "analysis_unit": "user",
                "reason_codes": [],
                "minimum_direct_design": "none",
            },
        },
        {
            "case_id": "anonymous-row-identity",
            "answers": {
                "verdict": "supported",
                "analysis_unit": "user",
                "reason_codes": [],
            },
        },
        {
            "case_id": "two-proportion-significance",
            "answers": {
                "verdict": "significant",
                "test": "two_sided_two_proportion_z",
                "p_value": 0.01,
            },
        },
        {
            "case_id": "mechanism-test-directness",
            "answers": {
                "verdict": "direct",
                "reason_codes": [],
                "required_changed_variable": "content_template",
            },
        },
        {
            "case_id": "baseline-carry-forward",
            "answers": {
                "verdict": "complete",
                "missing_baseline_finding_ids": [],
            },
        },
    ]
    return failing


class SemanticConformanceTests(unittest.TestCase):
    def test_pass_fixture_reports_each_dimension_separately(self) -> None:
        result = assess_semantic_conformance(
            responses_fixture(), expectations_fixture()
        )
        self.assertEqual(result["overall_result"], "passed")
        self.assertFalse(result["cross_host_claim_allowed"])
        self.assertEqual(
            set(result["dimension_results"]),
            {
                "causal_calibration",
                "unit_identity",
                "statistical_calibration",
                "mechanism_directness",
                "baseline_preservation",
            },
        )
        self.assertTrue(all(
            item["passed"] for item in result["dimension_results"].values()
        ))

    def test_failure_fixture_cannot_be_hidden_by_an_average_score(self) -> None:
        result = assess_semantic_conformance(
            responses_fixture(passed=False), expectations_fixture()
        )
        self.assertEqual(result["overall_result"], "failed")
        self.assertEqual(len(result["critical_failure_ids"]), 5)
        self.assertTrue(all(
            not item["passed"] for item in result["dimension_results"].values()
        ))

    def test_missing_case_is_incomplete_not_a_partial_pass(self) -> None:
        responses = responses_fixture()
        responses["cases"].pop()
        result = assess_semantic_conformance(
            responses, expectations_fixture()
        )
        self.assertEqual(result["overall_result"], "incomplete")
        self.assertEqual(result["missing_response_ids"], ["baseline-carry-forward"])

    def test_two_hosts_must_both_pass_every_dimension(self) -> None:
        first = assess_semantic_conformance(
            responses_fixture(), expectations_fixture()
        )
        second_responses = responses_fixture()
        second_responses.update({"host": "second-host", "run_id": "fixture-pass-2"})
        second = assess_semantic_conformance(
            second_responses, expectations_fixture()
        )
        result = compare_semantic_conformance([first, second])
        self.assertEqual(result["overall_result"], "passed")
        self.assertTrue(result["semantic_probe_stability_claim_allowed"])
        self.assertFalse(result["real_analysis_increment_claimed"])

    def test_cross_host_comparison_exposes_the_failed_host_by_dimension(self) -> None:
        first = assess_semantic_conformance(
            responses_fixture(), expectations_fixture()
        )
        failed_responses = responses_fixture(passed=False)
        failed_responses.update({"host": "second-host", "run_id": "fixture-fail-2"})
        second = assess_semantic_conformance(
            failed_responses, expectations_fixture()
        )
        result = compare_semantic_conformance([first, second])
        self.assertEqual(result["overall_result"], "failed")
        self.assertFalse(result["semantic_probe_stability_claim_allowed"])
        self.assertEqual(
            result["dimension_results"]["causal_calibration"]["failed_hosts"],
            ["second-host"],
        )


if __name__ == "__main__":
    unittest.main()
