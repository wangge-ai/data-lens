from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from _common import file_sha256, load_json, safe_number, write_json


ANALYSIS_VERSION = "operational-analysis/1.0"
DAILY_REQUIRED = ("business_date", "platform", "orders", "paid_amount")
SUM_FIELDS = ("orders", "paid_amount", "refund_amount", "promo_spend", "units", "after_sale_orders")


def parse_iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def pct_change(before: float | None, after: float | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return (after - before) / before


def sum_nullable(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [safe_number(row.get(field)) for row in rows]
    valid = [float(value) for value in values if value is not None]
    return sum(valid) if valid else None


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {field: rounded(sum_nullable(rows, field)) for field in SUM_FIELDS}
    orders = result.get("orders")
    paid = result.get("paid_amount")
    result["paid_per_order"] = rounded(paid / orders) if paid is not None and orders not in (None, 0) else None
    result["refund_rate_on_paid"] = rounded(result["refund_amount"] / paid) if result.get("refund_amount") is not None and paid not in (None, 0) else None
    result["promo_to_paid_ratio"] = rounded(result["promo_spend"] / paid) if result.get("promo_spend") is not None and paid not in (None, 0) else None
    return result


def choose_periods(payload: dict[str, Any], dates: list[str], errors: list[str]) -> list[dict[str, str]]:
    supplied = payload.get("periods") or []
    periods: list[dict[str, str]] = []
    if supplied:
        for item in supplied:
            start, end = parse_iso(item.get("start")), parse_iso(item.get("end"))
            if not start or not end or start > end or not item.get("id"):
                errors.append(f"invalid_period:{item}")
                continue
            periods.append({"id": str(item["id"]), "start": start.isoformat(), "end": end.isoformat()})
    elif dates:
        midpoint = max(1, len(dates) // 2)
        left, right = dates[:midpoint], dates[midpoint:]
        periods.append({"id": "period_1", "start": left[0], "end": left[-1]})
        if right:
            periods.append({"id": "period_2", "start": right[0], "end": right[-1]})
    occupied: dict[str, str] = {}
    for period in periods:
        cursor, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        while cursor <= end:
            key = cursor.isoformat()
            if key in occupied:
                errors.append(f"overlapping_periods:{occupied[key]}:{period['id']}:{key}")
            occupied[key] = period["id"]
            cursor += timedelta(days=1)
    return periods


def period_for(day: str, periods: list[dict[str, str]]) -> str | None:
    for period in periods:
        if period["start"] <= day <= period["end"]:
            return period["id"]
    return None


def aggregate_daily(rows: list[dict[str, Any]], errors: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        missing = [field for field in DAILY_REQUIRED if row.get(field) in (None, "")]
        if missing:
            errors.append(f"platform_daily_row_{index}_missing:{','.join(missing)}")
            continue
        day, platform_name = str(row["business_date"]), str(row["platform"]).strip()
        if not parse_iso(day):
            errors.append(f"platform_daily_row_{index}_invalid_business_date:{day}")
            continue
        negative_fields = [
            field for field in SUM_FIELDS
            if safe_number(row.get(field)) is not None and float(safe_number(row.get(field))) < 0
        ]
        if negative_fields:
            errors.append(f"platform_daily_row_{index}_negative:{','.join(negative_fields)}")
        grouped[(day, platform_name)].append(row)
    result: list[dict[str, Any]] = []
    for (day, platform_name), items in sorted(grouped.items()):
        if len(items) > 1:
            errors.append(f"duplicate_platform_daily_key:{day}:{platform_name}:{len(items)}")
        block = metric_block(items)
        units, orders = block.get("units"), block.get("orders")
        if units is not None and orders not in (None, 0) and units / orders > 100:
            warnings.append(f"implausible_units_per_order_candidate:{day}:{platform_name}:{rounded(units / orders, 2)}")
        result.append({"business_date": day, "platform": platform_name, **block})
    return result


def date_gap_warnings(daily: list[dict[str, Any]], warnings: list[str]) -> None:
    by_platform: dict[str, list[date]] = defaultdict(list)
    for row in daily:
        by_platform[row["platform"]].append(date.fromisoformat(row["business_date"]))
    for platform_name, days in by_platform.items():
        unique = sorted(set(days))
        for left, right in zip(unique, unique[1:]):
            if (right - left).days > 1:
                warnings.append(f"business_date_gap:{platform_name}:{left.isoformat()}:{right.isoformat()}")


def summarize(daily: list[dict[str, Any]], periods: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in daily:
        period_id = period_for(row["business_date"], periods)
        if period_id:
            groups[(period_id, row["platform"])].append(row)
            groups[(period_id, "全部平台")].append(row)
    return [
        {"period": period_id, "platform": platform_name, "days_observed": len({r['business_date'] for r in rows}), **metric_block(rows)}
        for (period_id, platform_name), rows in sorted(groups.items())
    ]


def compare_periods(summary: list[dict[str, Any]], periods: list[dict[str, str]]) -> list[dict[str, Any]]:
    if len(periods) < 2:
        return []
    before_id, after_id = periods[0]["id"], periods[1]["id"]
    lookup = {(row["period"], row["platform"]): row for row in summary}
    platforms = sorted({row["platform"] for row in summary})
    result: list[dict[str, Any]] = []
    for platform_name in platforms:
        before, after = lookup.get((before_id, platform_name)), lookup.get((after_id, platform_name))
        if not before or not after:
            result.append({"platform": platform_name, "before_period": before_id, "after_period": after_id, "comparison_status": "not_comparable_missing_period"})
            continue
        row: dict[str, Any] = {
            "platform": platform_name, "before_period": before_id, "after_period": after_id,
            "comparison_status": "comparable", "before": before, "after": after,
        }
        row["orders_change_pct"] = rounded(pct_change(before.get("orders"), after.get("orders")))
        row["paid_amount_change_pct"] = rounded(pct_change(before.get("paid_amount"), after.get("paid_amount")))
        row["paid_per_order_change_pct"] = rounded(pct_change(before.get("paid_per_order"), after.get("paid_per_order")))
        b_orders, a_orders = before.get("orders"), after.get("orders")
        b_rate = before.get("paid_amount") / b_orders if before.get("paid_amount") is not None and b_orders not in (None, 0) else None
        a_rate = after.get("paid_amount") / a_orders if after.get("paid_amount") is not None and a_orders not in (None, 0) else None
        if None not in (b_orders, a_orders, b_rate, a_rate):
            volume = (a_orders - b_orders) * (a_rate + b_rate) / 2
            structure = (a_rate - b_rate) * (a_orders + b_orders) / 2
            actual = after["paid_amount"] - before["paid_amount"]
            row["paid_amount_decomposition"] = {
                "volume_effect": rounded(volume),
                "paid_per_order_effect": rounded(structure),
                "actual_change": rounded(actual),
                "reconciliation_difference": rounded(actual - volume - structure),
                "method": "symmetric_two_factor_decomposition",
            }
        result.append(row)
    return result


def subphases(daily: list[dict[str, Any]], periods: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for period in periods:
        days = sorted({row["business_date"] for row in daily if period["start"] <= row["business_date"] <= period["end"]})
        if len(days) < 4:
            continue
        cut = len(days) // 2
        for label, selected in (("early", set(days[:cut])), ("late", set(days[cut:]))):
            rows = [row for row in daily if row["business_date"] in selected]
            result.append({"period": period["id"], "subphase": label, "start": min(selected), "end": max(selected), "platform": "全部平台", **metric_block(rows)})
            for platform_name in sorted({row["platform"] for row in rows}):
                platform_rows = [row for row in rows if row["platform"] == platform_name]
                result.append({"period": period["id"], "subphase": label, "start": min(selected), "end": max(selected), "platform": platform_name, **metric_block(platform_rows)})
    return result


def change_candidates(daily: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    platforms = sorted({row["platform"] for row in daily}) + ["全部平台"]
    for platform_name in platforms:
        rows = daily if platform_name == "全部平台" else [row for row in daily if row["platform"] == platform_name]
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_day[row["business_date"]].append(row)
        series = [(day, metric_block(items)) for day, items in sorted(by_day.items())]
        for (before_day, before), (after_day, after) in zip(series, series[1:]):
            for metric in ("orders", "paid_amount", "paid_per_order", "promo_spend"):
                change = pct_change(before.get(metric), after.get(metric))
                if change is not None and abs(change) >= threshold:
                    result.append({
                        "platform": platform_name, "metric": metric, "before_date": before_day,
                        "candidate_date": after_day, "change_pct": rounded(change),
                        "classification": "change_point_candidate_not_cause",
                    })
    return result


def entity_movements(rows: list[dict[str, Any]], entity_type: str, periods: list[dict[str, str]], top_n: int) -> dict[str, Any]:
    if len(periods) < 2:
        return {"entity_type": entity_type, "status": "needs_two_periods", "movements": []}
    first, second = periods[0]["id"], periods[1]["id"]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid = 0
    for row in rows:
        entity_id = row.get("entity_id") or row.get(f"{entity_type}_id")
        period_id, platform_name = row.get("period"), row.get("platform")
        if not entity_id or period_id not in {first, second} or not platform_name:
            invalid += 1
            continue
        groups[(str(entity_id), str(platform_name), str(period_id))].append(row)
    entity_keys = sorted({(entity_id, platform_name) for entity_id, platform_name, _ in groups})
    movements, only_before, only_after = [], [], []
    for entity_id, platform_name in entity_keys:
        before_rows = groups.get((entity_id, platform_name, first))
        after_rows = groups.get((entity_id, platform_name, second))
        if not before_rows:
            only_after.append({"entity_id": entity_id, "platform": platform_name, "status": "not_observed_before"})
            continue
        if not after_rows:
            only_before.append({"entity_id": entity_id, "platform": platform_name, "status": "not_observed_after"})
            continue
        before, after = metric_block(before_rows), metric_block(after_rows)
        change = None if before.get("paid_amount") in (None, 0) or after.get("paid_amount") is None else after["paid_amount"] - before["paid_amount"]
        movements.append({
            "entity_id": entity_id, "platform": platform_name, "before": before, "after": after,
            "paid_amount_change": rounded(change),
            "observation_status": "observed_in_both_periods",
            "source_rows_aggregated": len(before_rows) + len(after_rows),
        })
    movements.sort(key=lambda row: abs(row.get("paid_amount_change") or 0), reverse=True)
    return {
        "entity_type": entity_type,
        "status": "complete",
        "input_rows": len(rows),
        "invalid_rows": invalid,
        "comparable_entities": len(movements),
        "not_observed_before": only_after,
        "not_observed_after": only_before,
        "ranking_boundary": "Only entities observed in both periods are ranked. Absence from a ranking/export is not converted to zero.",
        "movements": movements[:top_n],
    }


def coverage_checks(rows: list[dict[str, Any]], warnings: list[str], threshold: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("family") or "unknown")].append(row)
    for family, items in groups.items():
        items.sort(key=lambda row: str(row.get("collection_date") or ""))
        for before, after in zip(items, items[1:]):
            flags: list[str] = []
            if before.get("schema_fingerprint") and after.get("schema_fingerprint") and before["schema_fingerprint"] != after["schema_fingerprint"]:
                flags.append("schema_changed")
            for metric in ("file_count", "row_count", "sku_count"):
                change = pct_change(safe_number(before.get(metric)), safe_number(after.get(metric)))
                if change is not None and abs(change) >= threshold:
                    flags.append(f"{metric}_jump")
            if flags:
                candidate = {
                    "family": family, "before_date": before.get("collection_date"),
                    "candidate_date": after.get("collection_date"), "flags": flags,
                    "classification": "coverage_break_candidate",
                }
                result.append(candidate)
                warnings.append(f"coverage_break_candidate:{family}:{after.get('collection_date')}:{','.join(flags)}")
    return result


def aggregate_optional_facts(
    rows: list[dict[str, Any]],
    date_field: str,
    dimension_fields: tuple[str, ...],
    metric_fields: tuple[str, ...],
    errors: list[str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        day = str(row.get(date_field) or "")
        platform_name = str(row.get("platform") or "").strip()
        if not parse_iso(day) or not platform_name:
            errors.append(f"optional_fact_invalid_key:{date_field}:{index}")
            continue
        key = tuple([day, platform_name] + [str(row.get(field) or "") for field in dimension_fields])
        groups[key].append(row)
    result: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        record: dict[str, Any] = {date_field: key[0], "platform": key[1]}
        for offset, field in enumerate(dimension_fields, start=2):
            record[field] = key[offset]
        for field in metric_fields:
            record[field] = rounded(sum_nullable(items, field))
        if "delayed_orders" in record and "shipped_orders" in record:
            record["delay_rate"] = rounded(record["delayed_orders"] / record["shipped_orders"]) if record.get("delayed_orders") is not None and record.get("shipped_orders") not in (None, 0) else None
        result.append(record)
    return result


def analyze(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("contract") != "corpus_lens_operational_facts/1.0":
        errors.append("unsupported_operational_facts_contract")
    daily = aggregate_daily(list(payload.get("platform_daily") or []), errors, warnings)
    if not daily:
        errors.append("platform_daily_empty")
    date_gap_warnings(daily, warnings)
    dates = sorted({row["business_date"] for row in daily})
    periods = choose_periods(payload, dates, errors)
    platforms = sorted({row["platform"] for row in daily})
    promo_known_by_platform: dict[str, list[bool]] = defaultdict(list)
    for row in daily:
        promo_known_by_platform[row["platform"]].append(row.get("promo_spend") is not None)
    for platform_name, states in promo_known_by_platform.items():
        if any(states) and not all(states):
            warnings.append(f"promo_spend_partial_missing_not_zero:{platform_name}")
    if not payload.get("time_contract"):
        warnings.append("time_contract_missing")
    summary = summarize(daily, periods)
    comparisons = compare_periods(summary, periods)
    coverage = coverage_checks(list(payload.get("coverage") or []), warnings, float(payload.get("coverage_jump_threshold") or 0.5))
    promo_daily = aggregate_optional_facts(
        list(payload.get("promo_daily") or []), "promotion_date", (),
        ("promo_spend", "paid_amount_attributed", "clicks", "impressions"), errors,
    )
    inventory = aggregate_optional_facts(
        list(payload.get("inventory_snapshot") or []), "snapshot_date", ("source_family",),
        ("sku_count", "available_stock", "outbound_7d", "slow_candidates", "stockout_candidates"), errors,
    )
    fulfillment = aggregate_optional_facts(
        list(payload.get("fulfillment_daily") or []), "business_date", (),
        ("shipped_orders", "delayed_orders", "canceled_orders", "delivered_orders"), errors,
    )
    threshold = float(payload.get("change_candidate_threshold") or 0.25)
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "route": "repeated_operational_tables",
        "analysis_unit": "business_date_x_platform",
        "platform_dimension": {"mandatory": True, "platforms": platforms},
        "periods": periods,
        "time_contract": payload.get("time_contract") or {},
        "metric_definitions": {
            "paid_per_order": "paid_amount / orders using the same platform and period denominator",
            "promo_to_paid_ratio": "promo_spend / paid_amount; this is not ROAS",
            "missing": "null or absent; never silently replaced with zero",
        },
        "platform_daily": daily,
        "period_platform_summary": summary,
        "period_comparisons": comparisons,
        "subphase_summary": subphases(daily, periods),
        "change_point_candidates": change_candidates(daily, threshold),
        "store_movements": entity_movements(list(payload.get("store_period") or []), "store", periods, int(payload.get("entity_top_n") or 20)),
        "product_movements": entity_movements(list(payload.get("product_period") or []), "product", periods, int(payload.get("entity_top_n") or 20)),
        "promotion_daily_summary": promo_daily,
        "inventory_snapshot_summary": inventory,
        "fulfillment_daily_summary": fulfillment,
        "coverage_break_candidates": coverage,
        "interpretation_order": [
            "total", "daily_trend", "stage_comparison", "platform_contribution",
            "volume_and_paid_per_order_decomposition", "within_stage_subphases",
            "store_and_product_movements", "quality_and_anomalies", "validation_actions",
        ],
        "causal_boundary": "Change points, coverage breaks, and associations are candidates for investigation, not proof of cause.",
    }
    quality = {
        "quality_contract": "operational-quality/1.0",
        "gate_status": "fail" if errors else "pass_with_warnings" if warnings else "pass",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "checks": {
            "platform_daily_rows": len(daily), "platforms": len(platforms), "business_dates": len(dates),
            "periods": len(periods), "coverage_break_candidates": len(coverage),
            "missing_is_zero": False, "platform_dimension_present": bool(platforms),
            "decomposition_reconciled": all(
                abs(float(row.get("paid_amount_decomposition", {}).get("reconciliation_difference") or 0)) < 0.01
                for row in comparisons if row.get("paid_amount_decomposition")
            ),
        },
    }
    return result, quality


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic deep analysis on normalized repeated operational facts.")
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = load_json(args.facts)
    analysis, quality = analyze(payload)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    analysis["source_artifact"] = {"path": str(args.facts.resolve()), "sha256": file_sha256(args.facts)}
    write_json(args.output_dir / "operational_analysis.json", analysis)
    write_json(args.output_dir / "operational_quality_gate.json", quality)
    print(json.dumps({"gate_status": quality["gate_status"], "errors": len(quality["errors"]), "warnings": len(quality["warnings"])}, ensure_ascii=False))
    raise SystemExit(0 if quality["gate_status"] != "fail" else 1)


if __name__ == "__main__":
    main()
