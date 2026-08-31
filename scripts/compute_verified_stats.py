from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import load_json, safe_number, write_json


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def numeric(row: dict[str, Any], key: str) -> float | None:
    value = safe_number(row.get(key))
    return float(value) if value is not None else None


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def read_metrics(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def group_summary(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    dependencies: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = numeric(row, "total_readers")
        if value is None:
            continue
        label = str(row.get(key) or "未分类")
        grouped[label].append(value)
        dependency = numeric(row, "recommendation_dependency")
        if dependency is not None:
            dependencies[label].append(dependency)
    result = []
    for label, values in grouped.items():
        result.append(
            {
                key: label,
                "articles": len(values),
                "mean_total_readers": round(statistics.fmean(values), 1),
                "median_total_readers": round(statistics.median(values), 1),
                "median_recommendation_dependency": round(statistics.median(dependencies[label]), 4) if dependencies[label] else None,
            }
        )
    return sorted(result, key=lambda item: item["median_total_readers"], reverse=True)


def feature_summary(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for flag, label in ((True, "有"), (False, "无")):
        selected = [numeric(row, "total_readers") for row in rows if bool_value(row.get(feature)) is flag]
        values = [value for value in selected if value is not None]
        result[label] = {
            "articles": len(values),
            "mean_total_readers": round(statistics.fmean(values), 1) if values else None,
            "median_total_readers": round(statistics.median(values), 1) if values else None,
        }
    return result


def feature_candidate(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    summary = feature_summary(rows, feature)
    with_values = summary["有"]
    without_values = summary["无"]
    with_median = with_values["median_total_readers"]
    without_median = without_values["median_total_readers"]
    ratio = None
    if with_median is not None and without_median not in (None, 0):
        ratio = round(float(with_median) / float(without_median), 4)
    minimum_group = min(int(with_values["articles"]), int(without_values["articles"]))
    return {
        "feature": feature,
        "analysis_unit": "article",
        "eligible_denominator": len(rows),
        "groups": summary,
        "median_ratio_with_vs_without": ratio,
        "interpretation_status": "exploratory_candidate" if minimum_group >= 3 else "insufficient_group_size",
        "minimum_group_size": minimum_group,
        "causal_claim_allowed": False,
    }


def article_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "publish_date": row.get("publish_date"),
        "title": row.get("source_title") or row.get("archive_title"),
        "total_readers": safe_number(row.get("total_readers")),
        "recommend_readers": safe_number(row.get("recommend_readers")),
        "recommendation_dependency": safe_number(row.get("recommendation_dependency")),
        "content_category": row.get("content_category"),
        "archive_path": row.get("archive_path"),
    }


def compute(rows: list[dict[str, Any]], raw_metrics: dict[str, Any] | None) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("source_match_type") == "exact"
        and row.get("source_evidence_level") == "confirmed_total"
        and numeric(row, "total_readers") is not None
    ]
    eligible.sort(key=lambda row: numeric(row, "total_readers") or 0, reverse=True)
    values = [numeric(row, "total_readers") for row in eligible]
    reader_values = [value for value in values if value is not None]
    coverage: dict[str, int] = defaultdict(int)
    for row in rows:
        coverage[str(row.get("source_evidence_level") or "unknown")] += 1

    account_totals: dict[str, Any] = {}
    if raw_metrics:
        channel_totals: dict[str, float] = defaultdict(float)
        for row in raw_metrics.get("daily_channel", []):
            value = safe_number(row.get("readers"))
            if value is not None:
                channel_totals[str(row.get("channel"))] += float(value)
        interaction_totals: dict[str, float] = defaultdict(float)
        for row in raw_metrics.get("daily_interactions", []):
            for key in ("shares", "favorites", "published_articles"):
                value = safe_number(row.get(key))
                if value is not None:
                    interaction_totals[key] += float(value)
        all_reads = channel_totals.get("全部", 0.0)
        recommend_reads = channel_totals.get("推荐", 0.0)
        account_totals = {
            "channel_totals": {key: int(value) if value.is_integer() else value for key, value in sorted(channel_totals.items())},
            "all_reads": int(all_reads) if all_reads.is_integer() else all_reads,
            "recommend_reads": int(recommend_reads) if recommend_reads.is_integer() else recommend_reads,
            "recommendation_share": round(recommend_reads / all_reads, 4) if all_reads else None,
            "shares": int(interaction_totals.get("shares", 0)),
            "favorites": int(interaction_totals.get("favorites", 0)),
            "published_articles": int(interaction_totals.get("published_articles", 0)),
        }

    top_three_sum = sum(reader_values[:3])
    eligible_sum = sum(reader_values)
    return {
        "stats_version": "1.1",
        "analysis_unit": "article",
        "eligibility_rule": "source_match_type == exact and source_evidence_level == confirmed_total and total_readers is present",
        "denominator": len(eligible),
        "population_count": len(rows),
        "excluded_count": len(rows) - len(eligible),
        "coverage": dict(sorted(coverage.items())),
        "distribution": {
            "count": len(reader_values),
            "sum": int(eligible_sum),
            "mean": round(statistics.fmean(reader_values), 1) if reader_values else None,
            "median": round(statistics.median(reader_values), 1) if reader_values else None,
            "p25": round(percentile(reader_values, 0.25) or 0, 1) if reader_values else None,
            "p75": round(percentile(reader_values, 0.75) or 0, 1) if reader_values else None,
            "top3_share": round(top_three_sum / eligible_sum, 4) if eligible_sum else None,
        },
        "top_articles": [article_projection(row) for row in eligible[:10]],
        "bottom_articles": [article_projection(row) for row in eligible[-10:]],
        "categories": group_summary(eligible, "content_category"),
        "title_features": {
            feature: feature_summary(eligible, feature)
            for feature in ("has_number", "has_first_person", "has_tutorial", "has_asset", "has_ecom")
        },
        "feature_candidates": [
            feature_candidate(eligible, feature)
            for feature in ("has_number", "has_first_person", "has_tutorial", "has_asset", "has_ecom")
        ],
        "account_totals": account_totals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute deterministic article statistics using explicit eligibility rules.")
    parser.add_argument("article_metrics_csv", type=Path)
    parser.add_argument("--metrics-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw_metrics = load_json(args.metrics_json) if args.metrics_json else None
    result = compute(read_metrics(args.article_metrics_csv), raw_metrics)
    write_json(args.output, result)
    print(f"stats={args.output} denominator={result['denominator']}")


if __name__ == "__main__":
    main()
