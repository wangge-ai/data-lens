from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import statistics
import unicodedata
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from _common import file_sha256, guard_cli_output, load_json, read_text_fallback, write_json


SPEC_VERSION = "data-lens-hypothesis-experiment/0.1"
RESULT_VERSION = "data-lens-hypothesis-experiment-result/0.2"
MODES = {"atomic_claims", "hypothesis_comparison"}
DIMENSIONS = ("direction", "time", "point", "path", "invalidation")
GRANULARITY_MINUTES = {
    "tick": 0.0,
    "intraday_1m": 1.0,
    "intraday_5m": 5.0,
    "intraday_15m": 15.0,
    "intraday_30m": 30.0,
    "intraday_60m": 60.0,
    "daily": 1440.0,
    "weekly": 10080.0,
    "monthly": 43830.0,
    "quarterly": 131490.0,
    "yearly": 525960.0,
}
AGGREGATES = {
    "first",
    "last",
    "min",
    "max",
    "mean",
    "median",
    "sum",
    "count",
    "period_change",
    "period_pct_change",
    "max_drawdown_pct",
    "date_of_min",
    "date_of_max",
    "time_of_min",
    "time_of_max",
    "proportion",
    "group_mean_difference",
    "group_median_difference",
    "group_rate_difference",
    "difference_in_differences",
    "subgroup_difference_spread",
    "lagged_pearson",
    "walk_forward_interval_mae",
    "rolling_origin_naive_mae",
}
OPERATORS = {
    "gt",
    "gte",
    "lt",
    "lte",
    "eq",
    "neq",
    "between",
    "outside",
    "abs_lte",
    "abs_gte",
    "approx_eq",
}
ANALYSIS_BINDING_TYPES = {
    "predictive": {"out_of_sample"},
    "causal": {"randomized_experiment", "identified_observational_estimate"},
    "decision": {"decision_analysis", "policy_evaluation"},
}


class ExperimentError(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ExperimentError(f"not numeric: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "").rstrip("%")
        try:
            number = float(text)
        except ValueError as exc:
            raise ExperimentError(f"not numeric: {value!r}") from exc
    if math.isnan(number) or math.isinf(number):
        raise ExperimentError(f"not finite: {value!r}")
    return number


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "有"}


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ExperimentError(f"invalid ISO date: {value!r}") from exc


def _temporal(value: Any, *, end_of_day: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.max if end_of_day else time.min)
    text = _text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        parsed_date = date.fromisoformat(text)
        return datetime.combine(parsed_date, time.max if end_of_day else time.min)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentError(f"invalid ISO date or timestamp: {value!r}") from exc


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 10)
    return value


def _load_rows(source: Any, base_dir: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(source, dict):
        raise ExperimentError("data_source must be an object")
    inline = source.get("rows")
    path_text = _text(source.get("path"))
    if (inline is None) == (not path_text):
        raise ExperimentError("data_source must contain exactly one of path or rows")
    if inline is not None:
        if not isinstance(inline, list) or not all(isinstance(row, dict) for row in inline):
            raise ExperimentError("data_source.rows must be an array of objects")
        canonical = json.dumps(
            inline, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return [dict(row) for row in inline], {
            "kind": "inline",
            "row_count": len(inline),
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }

    path = Path(path_text)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    path = path.resolve()
    if not path.is_file():
        raise ExperimentError(f"data source does not exist: {path}")
    format_name = _text(source.get("format")).lower() or path.suffix.lower().lstrip(".")
    if format_name == "csv":
        raw, encoding = read_text_fallback(path)
        reader = csv.DictReader(raw.splitlines())
        if not reader.fieldnames:
            raise ExperimentError("CSV data source has no header")
        rows = [dict(row) for row in reader]
        return rows, {"kind": "file", "format": "csv", "path": path_text, "encoding": encoding, "row_count": len(rows), "sha256": file_sha256(path)}
    if format_name == "json":
        payload = load_json(path)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ExperimentError("JSON data source must be an array of objects or an object with rows")
        return [dict(row) for row in rows], {"kind": "file", "format": "json", "path": path_text, "row_count": len(rows), "sha256": file_sha256(path)}
    raise ExperimentError(f"unsupported data format: {format_name!r}")


def _granularity_sufficient(available: str, required: str) -> bool:
    if available not in GRANULARITY_MINUTES or required not in GRANULARITY_MINUTES:
        return False
    return GRANULARITY_MINUTES[available] <= GRANULARITY_MINUTES[required]


def _filter_window(
    rows: list[dict[str, Any]],
    time_field: str,
    window: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(window, dict):
        raise ExperimentError("evaluation_window must be an object")
    start_text = _text(window.get("start"))
    end_text = _text(window.get("end"))
    start = _temporal(start_text)
    end = _temporal(end_text, end_of_day=True)
    if start > end:
        raise ExperimentError("evaluation_window.start must not be after end")
    if not time_field:
        raise ExperimentError("data_source.time_field is required for an evaluation window")
    selected: list[dict[str, Any]] = []
    invalid_time_count = 0
    for row in rows:
        try:
            observed = _temporal(row.get(time_field))
        except ExperimentError:
            invalid_time_count += 1
            continue
        if start <= observed <= end:
            selected.append(row)
    return selected, {
        "declared_start": start_text,
        "declared_end": end_text,
        "included_row_count": len(selected),
        "excluded_outside_window_count": len(rows) - len(selected) - invalid_time_count,
        "invalid_time_row_count": invalid_time_count,
        "window_expanded": False,
    }


def _ordered(rows: list[dict[str, Any]], time_field: str) -> list[dict[str, Any]]:
    if not time_field:
        return list(rows)
    try:
        return sorted(rows, key=lambda row: _temporal(row.get(time_field)))
    except ExperimentError as exc:
        raise ExperimentError(f"cannot order rows by {time_field!r}: {exc}") from exc


def _values(rows: list[dict[str, Any]], field: str) -> list[float]:
    if not field:
        raise ExperimentError("measurement.field is required")
    values: list[float] = []
    for row in rows:
        if row.get(field) in (None, ""):
            continue
        values.append(_number(row.get(field)))
    if not values:
        raise ExperimentError(f"no numeric values for field {field!r}")
    return values


def _predicate(value: Any, predicate: Any) -> bool:
    if not isinstance(predicate, dict):
        raise ExperimentError("predicate must be an object")
    operator = _text(predicate.get("operator"))
    if operator not in OPERATORS:
        raise ExperimentError(f"unsupported predicate operator: {operator!r}")
    target = predicate.get("value")
    if operator in {"between", "outside"}:
        if not isinstance(target, list) or len(target) != 2:
            raise ExperimentError(f"{operator} requires a two-value array")
        try:
            observed = _number(value)
            lower, upper = (_number(target[0]), _number(target[1]))
        except ExperimentError:
            observed = _temporal(value)
            lower, upper = (_temporal(target[0]), _temporal(target[1], end_of_day=True))
        inside = lower <= observed <= upper
        return inside if operator == "between" else not inside
    if operator in {"eq", "neq"}:
        try:
            equal = _number(value) == _number(target)
        except ExperimentError:
            try:
                equal = _temporal(value) == _temporal(target)
            except ExperimentError:
                equal = _text(value) == _text(target)
        return equal if operator == "eq" else not equal
    observed = _number(value)
    expected = _number(target)
    if operator == "gt":
        return observed > expected
    if operator == "gte":
        return observed >= expected
    if operator == "lt":
        return observed < expected
    if operator == "lte":
        return observed <= expected
    if operator == "abs_lte":
        return abs(observed) <= abs(expected)
    if operator == "abs_gte":
        return abs(observed) >= abs(expected)
    tolerance = _number(predicate.get("tolerance"))
    return abs(observed - expected) <= tolerance


def _rate(rows: list[dict[str, Any]], field: str, condition: Any) -> float:
    if not rows:
        raise ExperimentError("rate requires at least one row")
    matches = sum(1 for row in rows if _predicate(row.get(field), condition))
    return matches / len(rows)


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 3:
        raise ExperimentError("lagged_pearson requires at least three paired observations")
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    if denominator == 0:
        raise ExperimentError("lagged_pearson is undefined for a constant series")
    return numerator / denominator


def _measure(rows: list[dict[str, Any]], measurement: Any, time_field: str) -> dict[str, Any]:
    if not isinstance(measurement, dict):
        raise ExperimentError("measurement must be an object")
    kind = _text(measurement.get("kind"))
    if kind not in AGGREGATES:
        raise ExperimentError(f"unsupported measurement kind: {kind!r}")
    ordered = _ordered(rows, time_field)
    field = _text(measurement.get("field"))

    if kind == "count":
        return {"kind": kind, "value": len(ordered), "n": len(ordered)}
    if not ordered:
        raise ExperimentError("no rows inside the declared evaluation window")
    if kind == "proportion":
        value = _rate(ordered, field, measurement.get("condition"))
        return {"kind": kind, "value": _round(value), "n": len(ordered)}
    if kind.startswith("group_"):
        group_field = _text(measurement.get("group_field"))
        group_a = measurement.get("group_a")
        group_b = measurement.get("group_b")
        rows_a = [row for row in ordered if row.get(group_field) == group_a]
        rows_b = [row for row in ordered if row.get(group_field) == group_b]
        if not rows_a or not rows_b:
            raise ExperimentError("both comparison groups must contain observations")
        if kind == "group_rate_difference":
            value_a = _rate(rows_a, field, measurement.get("condition"))
            value_b = _rate(rows_b, field, measurement.get("condition"))
            n_a = len(rows_a)
            n_b = len(rows_b)
        else:
            values_a = _values(rows_a, field)
            values_b = _values(rows_b, field)
            aggregator = statistics.fmean if kind == "group_mean_difference" else statistics.median
            value_a = aggregator(values_a)
            value_b = aggregator(values_b)
            n_a = len(values_a)
            n_b = len(values_b)
        return {
            "kind": kind,
            "value": _round(value_a - value_b),
            "group_a": {"value": _round(value_a), "n": n_a},
            "group_b": {"value": _round(value_b), "n": n_b},
            "difference_definition": "group_a_minus_group_b",
        }
    if kind == "difference_in_differences":
        group_field = _text(measurement.get("group_field"))
        period_field = _text(measurement.get("period_field"))
        treated_value = measurement.get("treated_value")
        control_value = measurement.get("control_value")
        pre_value = measurement.get("pre_value")
        post_value = measurement.get("post_value")
        if not group_field or not period_field:
            raise ExperimentError("difference_in_differences requires group_field and period_field")
        if treated_value == control_value:
            raise ExperimentError("difference_in_differences requires distinct treated and control values")
        if pre_value == post_value:
            raise ExperimentError("difference_in_differences requires distinct pre and post values")
        pre_rows = [row for row in ordered if row.get(period_field) == pre_value]
        post_rows = [row for row in ordered if row.get(period_field) == post_value]
        if not pre_rows or not post_rows:
            raise ExperimentError("difference_in_differences requires observations in both periods")
        if max(_temporal(row.get(time_field)) for row in pre_rows) >= min(
            _temporal(row.get(time_field)) for row in post_rows
        ):
            raise ExperimentError("difference_in_differences requires every pre observation to precede every post observation")

        def cell(group: Any, period: Any) -> tuple[float, int]:
            selected = [
                row
                for row in ordered
                if row.get(group_field) == group and row.get(period_field) == period
            ]
            values = _values(selected, field)
            return statistics.fmean(values), len(values)

        treated_pre, n_treated_pre = cell(treated_value, pre_value)
        treated_post, n_treated_post = cell(treated_value, post_value)
        control_pre, n_control_pre = cell(control_value, pre_value)
        control_post, n_control_post = cell(control_value, post_value)
        treated_change = treated_post - treated_pre
        control_change = control_post - control_pre
        value = treated_change - control_change
        return {
            "kind": kind,
            "value": _round(value),
            "treated_change": _round(treated_change),
            "control_change": _round(control_change),
            "cells": {
                "treated_pre": {"value": _round(treated_pre), "n": n_treated_pre},
                "treated_post": {"value": _round(treated_post), "n": n_treated_post},
                "control_pre": {"value": _round(control_pre), "n": n_control_pre},
                "control_post": {"value": _round(control_post), "n": n_control_post},
            },
            "difference_definition": "(treated_post-treated_pre)-(control_post-control_pre)",
            "claim_boundary": "This is a cell-mean difference-in-differences contrast. It is not causal proof unless parallel trends, no anticipation, concurrent shocks, and unit-composition stability are separately supported.",
        }
    if kind == "subgroup_difference_spread":
        group_field = _text(measurement.get("group_field"))
        subgroup_field = _text(measurement.get("subgroup_field"))
        group_a = measurement.get("group_a")
        group_b = measurement.get("group_b")
        if not group_field or not subgroup_field:
            raise ExperimentError("subgroup_difference_spread requires group_field and subgroup_field")
        if group_a == group_b:
            raise ExperimentError("subgroup_difference_spread requires distinct comparison groups")
        subgroup_values = list(dict.fromkeys(row.get(subgroup_field) for row in ordered))
        effects: list[dict[str, Any]] = []
        for subgroup in subgroup_values:
            rows_a = [
                row for row in ordered
                if row.get(subgroup_field) == subgroup and row.get(group_field) == group_a
            ]
            rows_b = [
                row for row in ordered
                if row.get(subgroup_field) == subgroup and row.get(group_field) == group_b
            ]
            if not rows_a or not rows_b:
                continue
            try:
                values_a = _values(rows_a, field)
                values_b = _values(rows_b, field)
            except ExperimentError:
                continue
            value_a = statistics.fmean(values_a)
            value_b = statistics.fmean(values_b)
            effects.append({
                "subgroup": subgroup,
                "difference": _round(value_a - value_b),
                "group_a": {"value": _round(value_a), "n": len(values_a)},
                "group_b": {"value": _round(value_b), "n": len(values_b)},
            })
        if len(effects) < 2:
            raise ExperimentError("subgroup_difference_spread requires at least two subgroups with both comparison groups")
        differences = [float(item["difference"]) for item in effects]
        return {
            "kind": kind,
            "value": _round(max(differences) - min(differences)),
            "subgroup_effects": effects,
            "opposite_directions": min(differences) < 0 < max(differences),
            "difference_definition": "range of subgroup-specific group_a_minus_group_b mean differences",
            "claim_boundary": "Subgroup contrasts are descriptive heterogeneity candidates, not individualized causal effects.",
        }
    if kind == "lagged_pearson":
        x_field = _text(measurement.get("x_field"))
        y_field = _text(measurement.get("y_field"))
        lag = int(measurement.get("lag", 0))
        if lag < 0:
            raise ExperimentError("lag must be zero or positive")
        pairs = [(row.get(x_field), row.get(y_field)) for row in ordered]
        if lag:
            pairs = [(ordered[index].get(x_field), ordered[index + lag].get(y_field)) for index in range(len(ordered) - lag)]
        xs = [_number(x) for x, _ in pairs]
        ys = [_number(y) for _, y in pairs]
        return {"kind": kind, "value": _round(_pearson(xs, ys)), "n_pairs": len(pairs), "lag": lag}
    if kind == "walk_forward_interval_mae":
        event_field = _text(measurement.get("event_field"))
        minimum_history = int(measurement.get("minimum_history", 3))
        event_dates = [_iso_date(row.get(time_field)) for row in ordered if _truthy(row.get(event_field))]
        if len(event_dates) < minimum_history + 2:
            raise ExperimentError("not enough events for walk-forward interval evaluation")
        parsed = [date.fromisoformat(item) for item in event_dates]
        intervals = [(parsed[index] - parsed[index - 1]).days for index in range(1, len(parsed))]
        predictions: list[dict[str, Any]] = []
        errors: list[float] = []
        for index in range(minimum_history, len(intervals)):
            predicted = float(statistics.median(intervals[:index]))
            observed = float(intervals[index])
            errors.append(abs(predicted - observed))
            predictions.append({"event_date": event_dates[index + 1], "predicted_interval_days": predicted, "observed_interval_days": observed})
        return {"kind": kind, "value": _round(statistics.fmean(errors)), "prediction_count": len(predictions), "predictions": predictions}
    if kind == "rolling_origin_naive_mae":
        minimum_history = int(measurement.get("minimum_history", 3))
        horizon = int(measurement.get("horizon", 1))
        if minimum_history < 2 or horizon < 1:
            raise ExperimentError("rolling_origin_naive_mae requires minimum_history >= 2 and horizon >= 1")
        numeric_rows: list[tuple[dict[str, Any], float]] = []
        for row in ordered:
            if row.get(field) in (None, ""):
                continue
            numeric_rows.append((row, _number(row.get(field))))
        if len(numeric_rows) < minimum_history + horizon:
            raise ExperimentError("not enough observations for rolling-origin evaluation")
        observed_times = [_text(row.get(time_field)) for row, _ in numeric_rows]
        if any(not item for item in observed_times) or len(observed_times) != len(set(observed_times)):
            raise ExperimentError("rolling_origin_naive_mae requires one usable observation per unique timestamp")
        predictions: list[dict[str, Any]] = []
        errors: list[float] = []
        for origin in range(minimum_history - 1, len(numeric_rows) - horizon):
            target = origin + horizon
            predicted = numeric_rows[origin][1]
            observed = numeric_rows[target][1]
            absolute_error = abs(predicted - observed)
            errors.append(absolute_error)
            predictions.append({
                "origin_time": _text(numeric_rows[origin][0].get(time_field)),
                "target_time": _text(numeric_rows[target][0].get(time_field)),
                "predicted": _round(predicted),
                "observed": _round(observed),
                "absolute_error": _round(absolute_error),
            })
        return {
            "kind": kind,
            "value": _round(statistics.fmean(errors)),
            "prediction_count": len(predictions),
            "horizon": horizon,
            "horizon_unit": "usable_observations",
            "minimum_history": minimum_history,
            "predictions": predictions,
            "leakage_check": "each prediction uses only values at or before its rolling origin",
            "claim_boundary": "The horizon counts usable observations, not guaranteed calendar periods; inspect origin_time and target_time when cadence is irregular.",
        }

    numeric_rows: list[tuple[dict[str, Any], float]] = []
    for row in ordered:
        if row.get(field) in (None, ""):
            continue
        numeric_rows.append((row, _number(row.get(field))))
    if not numeric_rows:
        raise ExperimentError(f"no numeric values for field {field!r}")
    values = [value for _, value in numeric_rows]
    if kind == "first":
        value = values[0]
    elif kind == "last":
        value = values[-1]
    elif kind == "min":
        value = min(values)
    elif kind == "max":
        value = max(values)
    elif kind == "mean":
        value = statistics.fmean(values)
    elif kind == "median":
        value = statistics.median(values)
    elif kind == "sum":
        value = sum(values)
    elif kind == "period_change":
        value = values[-1] - values[0]
    elif kind == "period_pct_change":
        if values[0] == 0:
            raise ExperimentError("period_pct_change cannot use a zero first value")
        value = (values[-1] / values[0] - 1.0) * 100.0
    elif kind == "max_drawdown_pct":
        peak = values[0]
        drawdowns: list[float] = []
        for item in values:
            peak = max(peak, item)
            drawdowns.append((item / peak - 1.0) * 100.0 if peak else 0.0)
        value = min(drawdowns)
    elif kind in {"date_of_min", "date_of_max", "time_of_min", "time_of_max"}:
        target = min(values) if kind in {"date_of_min", "time_of_min"} else max(values)
        index = values.index(target)
        observed_time = numeric_rows[index][0].get(time_field)
        value = (
            _iso_date(observed_time)
            if kind in {"date_of_min", "date_of_max"}
            else _temporal(observed_time).isoformat()
        )
    else:  # pragma: no cover - guarded by AGGREGATES
        raise ExperimentError(f"unimplemented measurement kind: {kind}")
    return {"kind": kind, "value": _round(value), "n": len(values)}


def _component_result(
    component: dict[str, Any],
    rows: list[dict[str, Any]],
    available_granularity: str,
    time_field: str,
) -> dict[str, Any]:
    component_id = _text(component.get("component_id"))
    dimension = _text(component.get("dimension"))
    statement = _text(component.get("statement"))
    required_granularity = _text(component.get("required_granularity"))
    base = {
        "component_id": component_id,
        "dimension": dimension,
        "statement": statement,
        "required_granularity": required_granularity,
        "available_granularity": available_granularity,
        "evaluation_window_spec": component.get("evaluation_window"),
        "measurement_spec": component.get("measurement"),
    }
    if not _granularity_sufficient(available_granularity, required_granularity):
        return {
            **base,
            "status": "unverifiable",
            "reason": "available data is coarser than the claim requires",
            "window": None,
            "measurement": None,
        }
    try:
        selected, window = _filter_window(rows, time_field, component.get("evaluation_window"))
        measurement = _measure(selected, component.get("measurement"), time_field)
        matched = _predicate(measurement.get("value"), component.get("expectation"))
    except (ExperimentError, TypeError, ValueError) as exc:
        return {**base, "status": "unverifiable", "reason": str(exc), "window": None, "measurement": None}
    if dimension == "invalidation":
        status = "triggered" if matched else "not_triggered"
    else:
        status = "supported" if matched else "contradicted"
    return {**base, "status": status, "reason": None, "window": window, "measurement": measurement, "expectation": component.get("expectation")}


def _validate_common(spec: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(spec, dict):
        raise ExperimentError("experiment specification must be an object")
    if spec.get("contract_version") != SPEC_VERSION:
        raise ExperimentError("unsupported hypothesis experiment contract")
    errors: list[str] = []
    for field in ("experiment_id", "decision_question", "mode"):
        if not _text(spec.get(field)):
            errors.append(f"{field} is required")
    if _text(spec.get("mode")) not in MODES:
        errors.append("mode is invalid")
    binding = spec.get("analysis_binding")
    if binding is not None:
        if not isinstance(binding, dict):
            errors.append("analysis_binding must be an object")
        else:
            for field in ("analysis_layer", "target", "validation_type", "method", "component_id"):
                if not _text(binding.get(field)):
                    errors.append(f"analysis_binding.{field} is required")
            if not _text(binding.get("outcome_field")):
                errors.append("analysis_binding.outcome_field is required")
            layer = _text(binding.get("analysis_layer"))
            validation_type = _text(binding.get("validation_type"))
            if validation_type not in ANALYSIS_BINDING_TYPES.get(layer, set()):
                errors.append("analysis_binding.validation_type is incompatible with analysis_layer")
            design_refs = binding.get("design_evidence_refs")
            if not isinstance(design_refs, list) or not design_refs or not all(
                isinstance(item, str) and item.strip() for item in design_refs
            ):
                errors.append("analysis_binding.design_evidence_refs must be a non-empty string array")
            if _text(spec.get("mode")) != "atomic_claims":
                errors.append("analysis_binding is currently supported only for atomic_claims")
            if layer == "causal" and not _text(binding.get("identification_strategy")):
                errors.append("causal analysis_binding.identification_strategy is required")
            if layer == "causal" and (
                not _text(binding.get("intervention")) or not _text(binding.get("comparator"))
            ):
                errors.append("causal analysis_binding requires intervention and comparator")
            if layer == "causal" and any(
                binding.get(field) in (None, "")
                for field in (
                    "group_field", "intervention_value", "comparator_value"
                )
            ):
                errors.append(
                    "causal analysis_binding requires group_field, intervention_value, and comparator_value"
                )
            if layer == "predictive" and _text(binding.get("validation_design")) not in {
                "rolling_origin", "future_holdout"
            }:
                errors.append("predictive analysis_binding.validation_design is invalid")
            if layer == "predictive":
                for field in (
                    "horizon", "horizon_unit", "cutoff", "cutoff_mode", "metric",
                    "baseline_model", "baseline_kind",
                ):
                    if not _text(binding.get(field)):
                        errors.append(f"predictive analysis_binding.{field} is required")
                horizon_steps = binding.get("horizon_steps")
                if not isinstance(horizon_steps, int) or isinstance(horizon_steps, bool) or horizon_steps < 1:
                    errors.append("predictive analysis_binding.horizon_steps must be a positive integer")
                else:
                    expected_horizon = f"{horizon_steps} {_text(binding.get('horizon_unit'))}"
                    if binding.get("horizon") != expected_horizon:
                        errors.append(
                            "predictive analysis_binding.horizon must be derived from horizon_steps and horizon_unit"
                        )
                if binding.get("baseline_model") != binding.get("baseline_kind"):
                    errors.append(
                        "predictive analysis_binding.baseline_model must be derived from baseline_kind"
                    )
                expected_cutoff = (
                    "each rolling origin"
                    if binding.get("cutoff_mode") == "rolling_origin" else binding.get("cutoff")
                )
                if binding.get("cutoff") != expected_cutoff:
                    errors.append(
                        "predictive analysis_binding.cutoff must be derived from cutoff_mode"
                    )
            if layer == "decision" and (
                not _text(binding.get("evidence_basis"))
                or not _text(binding.get("utility_metric"))
                or not _text(binding.get("decision_threshold"))
            ):
                errors.append("decision analysis_binding requires evidence_basis, utility_metric, and decision_threshold")
    source = spec.get("data_source")
    if not isinstance(source, dict):
        errors.append("data_source must be an object")
        source = {}
    granularity = _text(source.get("granularity"))
    if granularity not in GRANULARITY_MINUTES:
        errors.append("data_source.granularity is invalid")
    if isinstance(binding, dict):
        data_refs = spec.get("data_evidence_refs")
        if not isinstance(data_refs, list) or not data_refs or not all(
            isinstance(item, str) and item.strip() for item in data_refs
        ):
            errors.append("analysis-bound execution requires data_evidence_refs")
        if source.get("rows") is not None:
            errors.append(
                "analysis-bound execution requires a file data_source so its bytes can be tied to evidence"
            )
    return source, errors


def _run_atomic(spec: dict[str, Any], rows: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    declared = spec.get("declared_dimensions")
    components = spec.get("components")
    errors: list[str] = []
    if not isinstance(declared, list) or not declared:
        errors.append("declared_dimensions must be a non-empty array")
        declared = []
    declared = [_text(item) for item in declared]
    if len(declared) != len(set(declared)) or any(item not in DIMENSIONS for item in declared):
        errors.append("declared_dimensions must contain unique supported dimensions")
    if not isinstance(components, list):
        errors.append("components must be an array")
        components = []
    seen_ids: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            errors.append("each component must be an object")
            continue
        component_id = _text(component.get("component_id"))
        dimension = _text(component.get("dimension"))
        if not component_id or component_id in seen_ids:
            errors.append("component_id must be present and unique")
        seen_ids.add(component_id)
        if dimension not in declared:
            errors.append(f"component {component_id!r} uses an undeclared dimension")
        if not _text(component.get("statement")):
            errors.append(f"component {component_id!r} statement is required")
    for dimension in declared:
        if not any(isinstance(item, dict) and _text(item.get("dimension")) == dimension for item in components):
            errors.append(f"declared dimension {dimension!r} has no component")
    binding = spec.get("analysis_binding")
    if isinstance(binding, dict):
        method = _text(binding.get("method"))
        component_id = _text(binding.get("component_id"))
        bound_component = next(
            (
                component for component in components
                if isinstance(component, dict) and _text(component.get("component_id")) == component_id
            ),
            None,
        )
        layer = _text(binding.get("analysis_layer"))
        validation_type = _text(binding.get("validation_type"))
        bound_method = _text((bound_component.get("measurement") or {}).get("kind")) if isinstance(bound_component, dict) else ""
        if not bound_component:
            errors.append("analysis_binding.component_id must reference an executed component")
        elif method != bound_method:
            errors.append("analysis_binding.method must match the bound component measurement kind")
        measurement_spec = (
            bound_component.get("measurement")
            if isinstance(bound_component, dict) and isinstance(bound_component.get("measurement"), dict)
            else {}
        )
        if _text(measurement_spec.get("field")) != _text(binding.get("outcome_field")):
            errors.append(
                "analysis_binding.outcome_field must match the bound measurement field"
            )
        if layer == "predictive" and method != "rolling_origin_naive_mae":
            errors.append(
                "predictive analysis_binding currently requires rolling_origin_naive_mae"
            )
        if layer == "predictive" and method == "rolling_origin_naive_mae" and _text(
            binding.get("validation_design")
        ) != "rolling_origin":
            errors.append("rolling_origin_naive_mae requires rolling_origin validation_design")
        if layer == "predictive" and method == "rolling_origin_naive_mae":
            if _text(binding.get("cutoff_mode")) != "rolling_origin":
                errors.append("rolling_origin_naive_mae requires rolling_origin cutoff_mode")
            if _text(binding.get("horizon_unit")) != "usable_observations":
                errors.append(
                    "rolling_origin_naive_mae horizon_unit must be usable_observations"
                )
            if _text(binding.get("baseline_kind")) != "last_observation":
                errors.append(
                    "rolling_origin_naive_mae baseline_kind must be last_observation"
                )
        if layer == "predictive" and isinstance(bound_component, dict):
            measurement = bound_component.get("measurement") or {}
            if binding.get("horizon_steps") != measurement.get("horizon", 1):
                errors.append("analysis_binding.horizon_steps must match the bound forecast measurement")
            if _text(binding.get("metric")).lower() != "mae":
                errors.append("the current forecast probes support MAE result binding only")
        if layer == "causal" and validation_type == "randomized_experiment" and method not in {
            "group_mean_difference", "group_median_difference", "group_rate_difference"
        }:
            errors.append("randomized causal binding requires a supported randomized group contrast")
        if layer == "causal" and validation_type == "randomized_experiment":
            for measurement_key, binding_key in (
                ("group_field", "group_field"),
                ("group_a", "intervention_value"),
                ("group_b", "comparator_value"),
            ):
                if measurement_spec.get(measurement_key) != binding.get(binding_key):
                    errors.append(
                        f"causal binding {binding_key} must match measurement {measurement_key}"
                    )
        if layer == "causal" and validation_type == "identified_observational_estimate" and method != "difference_in_differences":
            errors.append("observational causal binding currently requires difference_in_differences")
        if layer == "causal" and validation_type == "identified_observational_estimate":
            for measurement_key, binding_key in (
                ("group_field", "group_field"),
                ("treated_value", "intervention_value"),
                ("control_value", "comparator_value"),
            ):
                if measurement_spec.get(measurement_key) != binding.get(binding_key):
                    errors.append(
                        f"causal binding {binding_key} must match measurement {measurement_key}"
                    )
        if layer == "decision":
            errors.append("this runner cannot validate decision rules; use a decision-analysis result contract")
    if errors:
        return {"execution_status": "invalid_spec", "errors": errors, "dimensions": {}, "summary": {"total_label": None}}

    results = [
        _component_result(component, rows, _text(source.get("granularity")), _text(source.get("time_field")))
        for component in components
    ]
    dimensions: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        selected = [item for item in results if item["dimension"] == dimension]
        dimensions[dimension] = {
            "coverage": "assessed" if selected else "not_claimed",
            "components": selected,
        }
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "execution_status": "completed",
        "errors": [],
        "dimensions": dimensions,
        "summary": {
            "component_count": len(results),
            "status_counts": counts,
            "total_label": None,
            "note": "No overall label is emitted; each claimed dimension keeps its own outcome.",
        },
    }


def _run_comparison(spec: dict[str, Any], rows: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    candidate_id = _text(spec.get("candidate_id"))
    baseline_id = _text(spec.get("baseline_hypothesis_id"))
    candidate_hypothesis_id = _text(spec.get("candidate_hypothesis_id"))
    core = _text(spec.get("candidate_core_mechanism"))
    target = _text(spec.get("target_mechanism"))
    mechanism_variable = _text(spec.get("mechanism_variable"))
    probe_variable = _text(spec.get("changed_or_isolated_variable"))
    measurement_window_claim = _text(spec.get("measurement_window_claim"))
    distinguishing_observation = _text(spec.get("distinguishing_observation"))
    data_evidence_refs = spec.get("data_evidence_refs")
    hypotheses = spec.get("hypotheses")
    errors: list[str] = []
    for field, value in (
        ("candidate_id", candidate_id),
        ("baseline_hypothesis_id", baseline_id),
        ("candidate_hypothesis_id", candidate_hypothesis_id),
        ("candidate_core_mechanism", core),
        ("target_mechanism", target),
        ("mechanism_variable", mechanism_variable),
        ("changed_or_isolated_variable", probe_variable),
        ("measurement_window_claim", measurement_window_claim),
        ("distinguishing_observation", distinguishing_observation),
    ):
        if not value:
            errors.append(f"{field} is required")
    mechanism_bound = bool(core and target and _normalize(core) == _normalize(target))
    variable_bound = bool(mechanism_variable and probe_variable and _normalize(mechanism_variable) == _normalize(probe_variable))
    direct_binding = {
        "mechanism_bound": mechanism_bound,
        "mechanism_variable_bound": variable_bound,
        "valid": mechanism_bound and variable_bound,
    }
    if not isinstance(hypotheses, list) or len(hypotheses) < 2:
        errors.append("hypotheses must contain at least two predictions")
        hypotheses = []
    prediction_map: dict[str, Any] = {}
    for item in hypotheses:
        if not isinstance(item, dict):
            errors.append("each hypothesis must be an object")
            continue
        hypothesis_id = _text(item.get("hypothesis_id"))
        if not hypothesis_id or hypothesis_id in prediction_map:
            errors.append("hypothesis_id must be present and unique")
        prediction_map[hypothesis_id] = item.get("prediction")
        if not _text(item.get("statement")):
            errors.append(f"hypothesis {hypothesis_id!r} statement is required")
    if baseline_id not in prediction_map or candidate_hypothesis_id not in prediction_map:
        errors.append("baseline and candidate hypothesis IDs must both be declared")
    encoded = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in prediction_map.values()]
    if len(encoded) != len(set(encoded)):
        errors.append("hypothesis predictions must differ")
    required_granularity = _text(spec.get("required_granularity"))
    if required_granularity not in GRANULARITY_MINUTES:
        errors.append("required_granularity is invalid")
    if (
        not isinstance(data_evidence_refs, list)
        or not data_evidence_refs
        or not all(isinstance(item, str) and item.strip() for item in data_evidence_refs)
    ):
        errors.append("data_evidence_refs must contain the declared holdout evidence used by the experiment")
    if errors:
        return {"execution_status": "invalid_spec", "errors": errors, "direct_binding": direct_binding, "evidence_direction": "not_tested"}
    if not direct_binding["valid"]:
        return {
            "execution_status": "rejected_misaligned",
            "errors": ["the experiment changes or isolates a variable other than the declared core mechanism variable"],
            "direct_binding": direct_binding,
            "evidence_direction": "not_tested",
        }
    if not _granularity_sufficient(_text(source.get("granularity")), required_granularity):
        return {
            "execution_status": "unverifiable",
            "errors": ["available data is coarser than the experiment requires"],
            "direct_binding": direct_binding,
            "evidence_direction": "not_tested",
        }
    try:
        selected, window = _filter_window(rows, _text(source.get("time_field")), spec.get("evaluation_window"))
        measurement = _measure(selected, spec.get("measurement"), _text(source.get("time_field")))
        matches = {hypothesis_id: _predicate(measurement.get("value"), prediction) for hypothesis_id, prediction in prediction_map.items()}
    except (ExperimentError, TypeError, ValueError) as exc:
        return {
            "execution_status": "unverifiable",
            "errors": [str(exc)],
            "direct_binding": direct_binding,
            "evidence_direction": "not_tested",
        }
    supported = [hypothesis_id for hypothesis_id, matched in matches.items() if matched]
    if supported == [candidate_hypothesis_id]:
        direction = "supports_e1"
    elif supported == [baseline_id]:
        direction = "supports_e0"
    else:
        direction = "mixed"
    return {
        "execution_status": "completed",
        "errors": [],
        "direct_binding": direct_binding,
        "baseline_hypothesis_id": baseline_id,
        "candidate_hypothesis_id": candidate_hypothesis_id,
        "hypotheses": hypotheses,
        "test_binding": {
            "changed_variable": probe_variable,
            "measurement_window": measurement_window_claim,
            "distinguishing_observation": distinguishing_observation,
        },
        "execution_binding": {
            "mechanism_variable": mechanism_variable,
            "data_evidence_refs": [str(item).strip() for item in data_evidence_refs],
            "required_granularity": required_granularity,
            "available_granularity": _text(source.get("granularity")),
            "evaluation_window": spec.get("evaluation_window"),
            "measurement": spec.get("measurement"),
            "hypothesis_predictions": prediction_map,
        },
        "window": window,
        "measurement": measurement,
        "prediction_matches": matches,
        "supported_hypothesis_ids": supported,
        "discriminated": len(supported) == 1,
        "evidence_direction": direction,
    }


def run_hypothesis_experiment(spec: Any, base_dir: Path | None = None) -> dict[str, Any]:
    source, common_errors = _validate_common(spec)
    base = {
        "contract_version": RESULT_VERSION,
        "source_spec": copy.deepcopy(spec) if isinstance(spec, dict) else None,
        "experiment_id": _text(spec.get("experiment_id")) if isinstance(spec, dict) else "",
        "decision_question": _text(spec.get("decision_question")) if isinstance(spec, dict) else "",
        "mode": _text(spec.get("mode")) if isinstance(spec, dict) else "",
        "candidate_id": _text(spec.get("candidate_id")) if isinstance(spec, dict) else "",
        "target_mechanism": _text(spec.get("target_mechanism")) if isinstance(spec, dict) else "",
        "analysis_binding": spec.get("analysis_binding") if isinstance(spec, dict) else None,
        "data_evidence_refs": spec.get("data_evidence_refs") if isinstance(spec, dict) else None,
    }
    if common_errors:
        return {**base, "execution_status": "invalid_spec", "errors": common_errors, "data_profile": None}
    try:
        rows, data_profile = _load_rows(source, base_dir)
    except ExperimentError as exc:
        return {**base, "execution_status": "unverifiable", "errors": [str(exc)], "data_profile": None}
    if spec["mode"] == "atomic_claims":
        detail = _run_atomic(spec, rows, source)
    else:
        detail = _run_comparison(spec, rows, source)
    return {**base, "data_profile": data_profile, **detail}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic atomized claim scoring or a direct E0/E1 discriminating experiment."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.spec])
    result = run_hypothesis_experiment(load_json(args.spec), args.spec.resolve().parent)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "execution_status": result["execution_status"]}, ensure_ascii=False))
    return 0 if result["execution_status"] in {"completed", "unverifiable", "rejected_misaligned"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
