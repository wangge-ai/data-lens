from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _common import load_json, parse_date_text, safe_number, write_csv, write_json


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def cell(row: list[Any], index: int) -> Any:
    return row[index] if 0 <= index < len(row) else None


def find_blocks(rows: list[list[Any]]) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    for row_index, row in enumerate(rows[:40]):
        for col_index, value in enumerate(row):
            current = text(value)
            window = [text(cell(row, col_index + offset)) for offset in range(6)]
            joined = "|".join(window)
            if current == "日期" and "渠道" in text(cell(row, col_index + 1)) and "阅读人数" in text(cell(row, col_index + 2)):
                found.setdefault("daily_channel", (row_index, col_index))
            if current == "日期" and "分享" in joined and "收藏" in joined and ("发布" in joined or "发表" in joined):
                found.setdefault("daily_interactions", (row_index, col_index))
            if (
                ("渠道" in current or "来源" in current)
                and ("内容日期" in joined or "发表日期" in joined or "发布日期" in joined)
                and "内容标题" in joined
                and "阅读人数" in joined
            ):
                found.setdefault("article_source", (row_index, col_index))
    return found


def rows_below(rows: list[list[Any]], header_row: int, start_col: int, width: int) -> list[list[Any]]:
    result: list[list[Any]] = []
    empty_run = 0
    for row in rows[header_row + 1 :]:
        values = [cell(row, start_col + offset) for offset in range(width)]
        if all(value in (None, "") for value in values):
            empty_run += 1
            if empty_run >= 20:
                break
            continue
        empty_run = 0
        result.append(values)
    return result


def extract(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("files"):
        raise ValueError("Parsed table JSON contains no files.")
    candidates: list[tuple[str, str, list[list[Any]], dict[str, tuple[int, int]]]] = []
    for file_item in payload["files"]:
        for sheet in file_item.get("sheets", []):
            rows = sheet.get("rows", [])
            blocks = find_blocks(rows)
            candidates.append((file_item["path"], sheet.get("name", "Sheet"), rows, blocks))
    candidates.sort(key=lambda item: len(item[3]), reverse=True)
    if not candidates or len(candidates[0][3]) < 2:
        raise ValueError("Could not identify the WeChat tendency tables. Expected Chinese headers for date/channel, interactions, and article sources.")
    source_path, sheet_name, rows, blocks = candidates[0]

    daily_channel: list[dict[str, Any]] = []
    if "daily_channel" in blocks:
        header_row, start = blocks["daily_channel"]
        for values in rows_below(rows, header_row, start, 3):
            parsed_date = parse_date_text(values[0])
            readers = safe_number(values[2])
            if parsed_date and text(values[1]) and readers is not None:
                daily_channel.append({"date": parsed_date, "channel": text(values[1]), "readers": readers})

    daily_interactions: list[dict[str, Any]] = []
    if "daily_interactions" in blocks:
        header_row, start = blocks["daily_interactions"]
        for values in rows_below(rows, header_row, start, 5):
            parsed_date = parse_date_text(values[0])
            if parsed_date:
                daily_interactions.append(
                    {
                        "date": parsed_date,
                        "shares": safe_number(values[1]),
                        "original_link_clicks": safe_number(values[2]),
                        "favorites": safe_number(values[3]),
                        "published_articles": safe_number(values[4]),
                    }
                )

    article_source: list[dict[str, Any]] = []
    if "article_source" in blocks:
        header_row, start = blocks["article_source"]
        for values in rows_below(rows, header_row, start, 5):
            parsed_date = parse_date_text(values[1])
            readers = safe_number(values[3])
            if parsed_date and text(values[2]) and readers is not None:
                article_source.append(
                    {
                        "source_channel": text(values[0]),
                        "publish_date": parsed_date,
                        "source_title": text(values[2]),
                        "readers": readers,
                        "read_share": safe_number(values[4]),
                    }
                )

    return {
        "wechat_metrics_version": "1.0",
        "source_path": source_path,
        "sheet_name": sheet_name,
        "identified_blocks": {key: {"header_row_1based": value[0] + 1, "start_col_1based": value[1] + 1} for key, value in blocks.items()},
        "coverage": {
            "daily_channel_rows": len(daily_channel),
            "daily_interaction_rows": len(daily_interactions),
            "article_source_rows": len(article_source),
        },
        "daily_channel": daily_channel,
        "daily_interactions": daily_interactions,
        "article_source": article_source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract normalized WeChat account metrics from parsed tendency export JSON.")
    parser.add_argument("parsed_table", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv-dir", type=Path)
    args = parser.parse_args()
    result = extract(load_json(args.parsed_table))
    write_json(args.output, result)
    if args.csv_dir:
        write_csv(args.csv_dir / "wechat-daily-channel.csv", ["date", "channel", "readers"], result["daily_channel"])
        write_csv(
            args.csv_dir / "wechat-daily-interactions.csv",
            ["date", "shares", "original_link_clicks", "favorites", "published_articles"],
            result["daily_interactions"],
        )
        write_csv(
            args.csv_dir / "wechat-article-source.csv",
            ["source_channel", "publish_date", "source_title", "readers", "read_share"],
            result["article_source"],
        )
    print(f"metrics={args.output} article_rows={len(result['article_source'])}")


if __name__ == "__main__":
    main()
