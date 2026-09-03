from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, parse_date_text, safe_number, write_json


METHOD_VERSION = "1.0.0"


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if path.suffix.lower() not in {".csv", ".tsv"}:
        raise ValueError("tabular_analysis accepts CSV or TSV; convert workbooks with parse_tabular_exports.py first")
    raw = path.read_text(encoding="utf-8-sig")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        dialect = csv.Sniffer().sniff(raw[:8192], delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("table has no header")
    headers = [str(field).strip() for field in reader.fieldnames]
    if any(not field for field in headers) or len(headers) != len(set(headers)):
        raise ValueError("table headers must be non-empty and unique")
    rows = [{header: row.get(original, "") for header, original in zip(headers, reader.fieldnames, strict=True)} for row in reader]
    if not rows:
        raise ValueError("table has no data rows")
    return headers, rows


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def profile(headers: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for header in headers:
        raw_values = [row.get(header, "") for row in rows]
        missing = sum(value is None or str(value).strip() == "" for value in raw_values)
        numeric = [number for value in raw_values if (number := safe_number(value)) is not None]
        numeric_values = [float(value) for value in numeric]
        item: dict[str, Any] = {
            "column": header,
            "row_count": len(rows),
            "missing_count": missing,
            "zero_count": sum(value == 0 for value in numeric),
            "unique_non_missing_count": len({str(value) for value in raw_values if value is not None and str(value).strip()}),
            "inferred_type": "numeric" if len(numeric_values) == len(rows) - missing and numeric_values else "mixed_or_text",
        }
        if numeric_values:
            item["numeric"] = {
                "valid_count": len(numeric_values),
                "minimum": min(numeric_values),
                "q1": _percentile(numeric_values, 0.25),
                "median": statistics.median(numeric_values),
                "mean": statistics.fmean(numeric_values),
                "q3": _percentile(numeric_values, 0.75),
                "maximum": max(numeric_values),
            }
        columns.append(item)
    return {
        "result_type": "data_profile",
        "row_count": len(rows),
        "column_count": len(headers),
        "columns": columns,
        "boundaries": ["inferred types are deterministic candidates and do not replace a confirmed data dictionary"],
    }


def grouped(rows: list[dict[str, str]], groups: list[str], metrics: list[str]) -> dict[str, Any]:
    if not groups or not metrics:
        raise ValueError("grouped analysis requires at least one group and one metric")
    buckets: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(str(row.get(group, "")).strip() or "__MISSING__" for group in groups)].append(row)
    output: list[dict[str, Any]] = []
    for key, members in sorted(buckets.items()):
        item: dict[str, Any] = {group: value for group, value in zip(groups, key, strict=True)}
        item["row_count"] = len(members)
        item["metrics"] = {}
        for metric in metrics:
            values = [float(value) for member in members if (value := safe_number(member.get(metric))) is not None]
            item["metrics"][metric] = {
                "valid_count": len(values),
                "missing_or_invalid_count": len(members) - len(values),
                "sum": sum(values) if values else None,
                "mean": statistics.fmean(values) if values else None,
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
            }
        output.append(item)
    return {
        "result_type": "grouped_descriptive",
        "group_keys": groups,
        "metrics": metrics,
        "groups": output,
        "boundaries": ["group differences are descriptive and do not establish causality"],
    }


def anomaly_candidates(rows: list[dict[str, str]], metric: str, threshold: float) -> dict[str, Any]:
    observed = [(index + 2, float(value)) for index, row in enumerate(rows) if (value := safe_number(row.get(metric))) is not None]
    values = [value for _, value in observed]
    if len(values) < 5:
        raise ValueError("robust anomaly candidates require at least five numeric values")
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    candidates = []
    if mad > 0:
        for row_number, value in observed:
            score = 0.6745 * (value - median) / mad
            if abs(score) >= threshold:
                candidates.append({"row_number": row_number, "value": value, "robust_z": score, "status": "candidate_not_error"})
    return {
        "result_type": "robust_anomaly_candidates",
        "metric": metric,
        "eligible_count": len(values),
        "median": median,
        "mad": mad,
        "threshold": threshold,
        "candidates": candidates,
        "boundaries": ["anomaly candidates are unusual under this rule; they are not automatically errors, fraud, or bad outcomes"],
    }


def change_candidate(rows: list[dict[str, str]], time_field: str, metric: str, minimum_segment: int) -> dict[str, Any]:
    observed: list[tuple[str, float, int]] = []
    for index, row in enumerate(rows):
        date_value = parse_date_text(row.get(time_field))
        number = safe_number(row.get(metric))
        if date_value is not None and number is not None:
            observed.append((date_value, float(number), index + 2))
    observed.sort(key=lambda item: (item[0], item[2]))
    if len(observed) < minimum_segment * 2:
        raise ValueError("change candidate requires at least two eligible segments")
    best: dict[str, Any] | None = None
    for split in range(minimum_segment, len(observed) - minimum_segment + 1):
        before = [value for _, value, _ in observed[:split]]
        after = [value for _, value, _ in observed[split:]]
        mean_before = statistics.fmean(before)
        mean_after = statistics.fmean(after)
        scale = statistics.pstdev([value for _, value, _ in observed]) or 1.0
        score = abs(mean_after - mean_before) / scale
        candidate = {
            "split_after": observed[split - 1][0],
            "split_before": observed[split][0],
            "before_count": len(before),
            "after_count": len(after),
            "before_mean": mean_before,
            "after_mean": mean_after,
            "standardized_mean_shift": score,
        }
        if best is None or candidate["standardized_mean_shift"] > best["standardized_mean_shift"]:
            best = candidate
    return {
        "result_type": "change_point_candidate",
        "time_field": time_field,
        "metric": metric,
        "eligible_count": len(observed),
        "candidate": best,
        "boundaries": ["the selected split maximizes an exploratory mean shift; it does not prove a structural break or its cause"],
    }


def method_result(method_id: str, source: Path, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": method_id,
        "method_version": METHOD_VERSION,
        "status": "succeeded",
        "source_sha256": file_sha256(source),
        "results": [result],
        "diagnostics": [],
        "boundaries": result.get("boundaries", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run portable deterministic Data Lens table methods on CSV/TSV input.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("profile", "group", "anomaly", "change"):
        command = subparsers.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name == "group":
            command.add_argument("--group", action="append", required=True)
            command.add_argument("--metric", action="append", required=True)
        elif name == "anomaly":
            command.add_argument("--metric", required=True)
            command.add_argument("--threshold", type=float, default=3.5)
        elif name == "change":
            command.add_argument("--time-field", required=True)
            command.add_argument("--metric", required=True)
            command.add_argument("--minimum-segment", type=int, default=3)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.source])
    headers, rows = read_table(args.source)
    if args.command == "profile":
        result = profile(headers, rows)
        method_id = "data_lens.table_profile"
    elif args.command == "group":
        unknown = (set(args.group) | set(args.metric)) - set(headers)
        if unknown:
            parser.error("unknown columns: " + ", ".join(sorted(unknown)))
        result = grouped(rows, args.group, args.metric)
        method_id = "data_lens.grouped_descriptive"
    elif args.command == "anomaly":
        if args.metric not in headers:
            parser.error(f"unknown metric: {args.metric}")
        result = anomaly_candidates(rows, args.metric, args.threshold)
        method_id = "data_lens.robust_anomaly_candidates"
    else:
        unknown = {args.time_field, args.metric} - set(headers)
        if unknown:
            parser.error("unknown columns: " + ", ".join(sorted(unknown)))
        result = change_candidate(rows, args.time_field, args.metric, args.minimum_segment)
        method_id = "data_lens.change_point_candidate"
    payload = method_result(method_id, args.source, result)
    write_json(args.output, payload)
    print(json.dumps({"output": str(args.output), "method_id": method_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
