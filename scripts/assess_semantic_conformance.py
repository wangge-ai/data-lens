from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json


RESPONSE_VERSION = "data-lens-semantic-conformance-responses/0.1"
EXPECTATION_VERSION = "data-lens-semantic-conformance-expectations/0.1"


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), expected, rel_tol=1e-9, abs_tol=1e-9)
    return actual == expected


def assess_semantic_conformance(
    responses: Any,
    expectations: Any,
) -> dict[str, Any]:
    if not isinstance(responses, dict) or responses.get("contract_version") != RESPONSE_VERSION:
        raise ValueError("unsupported semantic conformance response contract")
    if not isinstance(expectations, dict) or expectations.get("contract_version") != EXPECTATION_VERSION:
        raise ValueError("unsupported semantic conformance expectation contract")
    host = str(responses.get("host") or "").strip()
    model = str(responses.get("model") or "").strip()
    run_id = str(responses.get("run_id") or "").strip()
    if not host or not model or not run_id:
        raise ValueError("responses require host, model, and run_id")
    rows = responses.get("cases")
    if not isinstance(rows, list):
        raise ValueError("responses.cases must be an array")
    by_id = {
        str(row.get("case_id") or "").strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("case_id") or "").strip()
    }


    case_results: list[dict[str, Any]] = []
    dimension_results: dict[str, dict[str, Any]] = {}
    for expected in expectations.get("cases") or []:
        case_id = str(expected.get("case_id") or "").strip()
        dimension = str(expected.get("dimension") or "").strip()
        response = by_id.get(case_id)
        checks: list[dict[str, Any]] = []
        if response is None:
            checks.append({"check": "response_present", "passed": False, "detail": "missing"})
            answers: dict[str, Any] = {}
        else:
            answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
            checks.append({
                "check": "response_present",
                "passed": isinstance(response.get("answers"), dict),
                "detail": "answers must be an object",
            })
        for field, value in (expected.get("equals") or {}).items():
            actual = answers.get(field)
            checks.append({
                "check": f"equals:{field}",
                "passed": _same(actual, value),
                "expected": value,
                "actual": actual,
            })
        for field, required_values in (expected.get("includes") or {}).items():
            actual = answers.get(field)
            actual_values = set(actual) if isinstance(actual, list) else set()
            missing = [value for value in required_values if value not in actual_values]
            checks.append({
                "check": f"includes:{field}",
                "passed": not missing,
                "expected": required_values,
                "actual": actual,
                "missing": missing,
            })
        for field, rule in (expected.get("numeric") or {}).items():
            actual = answers.get(field)
            expected_value = rule.get("value")
            tolerance = rule.get("absolute_tolerance", 0.0)
            passed = (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and isinstance(expected_value, (int, float))
                and abs(float(actual) - float(expected_value)) <= float(tolerance)
            )
            checks.append({
                "check": f"numeric:{field}",
                "passed": passed,
                "expected": expected_value,
                "absolute_tolerance": tolerance,
                "actual": actual,
            })
        passed = bool(checks) and all(check["passed"] for check in checks)
        case_results.append({
            "case_id": case_id,
            "dimension": dimension,
            "critical": expected.get("critical") is True,
            "passed": passed,
            "checks": checks,
        })
        bucket = dimension_results.setdefault(
            dimension,
            {"passed": True, "case_ids": [], "failed_case_ids": []},
        )
        bucket["case_ids"].append(case_id)
        if not passed:
            bucket["passed"] = False
            bucket["failed_case_ids"].append(case_id)

    critical_failures = [
        item["case_id"] for item in case_results
        if item["critical"] and not item["passed"]
    ]
    missing_response_ids = [
        item["case_id"] for item in case_results
        if any(check["check"] == "response_present" and not check["passed"] for check in item["checks"])
    ]
    overall = (
        "incomplete" if missing_response_ids
        else "passed" if case_results and all(item["passed"] for item in case_results)
        else "failed"
    )
    return {
        "contract_version": "data-lens-semantic-conformance-assessment/0.1",
        "host": host,
        "model": model,
        "run_id": run_id,
        "overall_result": overall,
        "cross_host_claim_allowed": False,
        "dimension_results": dimension_results,
        "case_results": case_results,
        "critical_failure_ids": critical_failures,
        "missing_response_ids": missing_response_ids,
        "interpretation": (
            "This single-host run passed the shared semantic probes; compare independent runs before making a cross-host stability claim."
            if overall == "passed"
            else "Semantic behavior is not conformant; package or syntax compatibility must not be reported as cross-host analytical stability."
        ),
    }


def compare_semantic_conformance(
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    hosts = [str(item.get("host") or "").strip() for item in assessments]
    distinct_hosts = sorted(set(hosts))
    dimensions = sorted({
        dimension
        for item in assessments
        for dimension in (item.get("dimension_results") or {})
    })
    dimension_results: dict[str, dict[str, Any]] = {}
    for dimension in dimensions:
        by_host = {
            str(item.get("host") or ""): bool(
                (item.get("dimension_results") or {}).get(dimension, {}).get("passed")
            )
            for item in assessments
        }
        dimension_results[dimension] = {
            "passed": len(by_host) == len(distinct_hosts) and all(by_host.values()),
            "by_host": by_host,
            "failed_hosts": sorted(host for host, passed in by_host.items() if not passed),
        }
    complete = (
        len(assessments) >= 2
        and len(distinct_hosts) >= 2
        and all(item.get("overall_result") != "incomplete" for item in assessments)
    )
    passed = (
        complete
        and all(item.get("overall_result") == "passed" for item in assessments)
        and bool(dimension_results)
        and all(item["passed"] for item in dimension_results.values())
    )
    overall = "passed" if passed else "incomplete" if not complete else "failed"
    return {
        "contract_version": "data-lens-cross-host-semantic-comparison/0.1",
        "overall_result": overall,
        "hosts": [
            {
                "host": item.get("host"),
                "model": item.get("model"),
                "run_id": item.get("run_id"),
                "overall_result": item.get("overall_result"),
            }
            for item in assessments
        ],
        "dimension_results": dimension_results,
        "semantic_probe_stability_claim_allowed": passed,
        "real_analysis_increment_claimed": False,
        "interpretation": (
            "Every tested host passed every shared semantic probe. This supports semantic-probe stability only; a full blind task is still required for analytical increment."
            if passed
            else "Cross-host semantic consistency was not established; inspect each failed dimension rather than averaging results."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess one host's answers to shared Data Lens semantic probes."
    )
    parser.add_argument("--responses", type=Path, nargs="+", required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [*args.responses, args.expectations])
    expectation_payload = load_json(args.expectations)
    assessments = [
        assess_semantic_conformance(load_json(path), expectation_payload)
        for path in args.responses
    ]
    result = (
        assessments[0]
        if len(assessments) == 1
        else compare_semantic_conformance(assessments)
    )
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "overall_result": result["overall_result"],
        "dimension_results": result["dimension_results"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
