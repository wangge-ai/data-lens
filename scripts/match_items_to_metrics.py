from __future__ import annotations

import argparse
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from _common import (
    classify_title,
    load_json,
    normalize_title,
    title_features,
    write_csv,
    write_json,
)


CHANNEL_COLUMNS = {
    "公众号消息": "official_account_message_readers",
    "公众号主页": "official_account_home_readers",
    "聊天会话": "chat_readers",
    "朋友圈": "moments_readers",
    "其他": "other_readers",
    "搜一搜": "search_readers",
    "搜索": "search_readers",
    "推荐": "recommend_readers",
}

FIELDS = [
    "publish_date",
    "archive_title",
    "archive_path",
    "content_category",
    "body_chars_approx",
    "paragraphs_approx",
    "image_refs",
    "headings",
    "bold_pairs",
    "has_number",
    "has_first_person",
    "has_tutorial",
    "has_asset",
    "has_ecom",
    "source_title",
    "source_match_type",
    "match_review_status",
    "title_similarity",
    "source_evidence_level",
    "total_readers",
    "recommend_readers",
    "recommendation_dependency",
    "daily_shares_signal",
    "daily_favorites_signal",
    "daily_published_articles",
    "known_source_rows",
    "official_account_message_readers",
    "official_account_home_readers",
    "chat_readers",
    "moments_readers",
    "other_readers",
    "search_readers",
]


def choose_source_group(
    article: dict[str, Any],
    source_groups: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[tuple[str, str] | None, str, float]:
    date = article.get("publish_date")
    title_norm = article.get("title_norm") or normalize_title(article.get("title"))
    exact_key = (date, title_norm)
    if exact_key in source_groups:
        return exact_key, "exact", 1.0
    candidates: list[tuple[float, tuple[str, str]]] = []
    for key in source_groups:
        if key[0] == date:
            candidates.append((SequenceMatcher(None, title_norm, key[1]).ratio(), key))
    if not candidates:
        return None, "none", 0.0
    candidates.sort(reverse=True, key=lambda item: item[0])
    best_score, best_key = candidates[0]
    if best_score < 0.72:
        return None, "none", best_score
    if len(candidates) > 1 and candidates[1][0] >= 0.72 and best_score - candidates[1][0] < 0.03:
        return None, "ambiguous", best_score
    return best_key, "same_date_fuzzy", best_score


def match(inventory: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    articles = [
        item
        for item in inventory.get("files", [])
        if item.get("canonical") and item.get("extension") == ".md" and item.get("evidence_role") == "content_text"
    ]
    source_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metrics.get("article_source", []):
        key = (row.get("publish_date"), normalize_title(row.get("source_title")))
        source_groups[key].append(row)
    interactions = {row.get("date"): row for row in metrics.get("daily_interactions", [])}

    records: list[dict[str, Any]] = []
    used_keys: set[tuple[str, str]] = set()
    for article in articles:
        key, match_type, similarity = choose_source_group(article, source_groups)
        rows = source_groups.get(key, []) if key else []
        if key:
            used_keys.add(key)
        channel_map: dict[str, float | int] = {}
        source_title = None
        for row in rows:
            source_title = source_title or row.get("source_title")
            channel = str(row.get("source_channel", ""))
            readers = row.get("readers")
            if readers is not None and (channel not in channel_map or readers > channel_map[channel]):
                channel_map[channel] = readers
        total = channel_map.get("全部")
        recommend = channel_map.get("推荐")
        if match_type == "ambiguous":
            evidence_level = "ambiguous_match"
        elif total is not None:
            evidence_level = "confirmed_total"
        elif channel_map:
            evidence_level = "partial_channels_only"
        else:
            evidence_level = "no_metric_row"
        day = interactions.get(article.get("publish_date"), {})
        title = article.get("title") or article.get("name") or ""
        record: dict[str, Any] = {
            "publish_date": article.get("publish_date"),
            "archive_title": title,
            "archive_path": article.get("path"),
            "content_category": classify_title(title),
            "body_chars_approx": article.get("body_chars_approx"),
            "paragraphs_approx": article.get("paragraphs_approx"),
            "image_refs": article.get("image_refs"),
            "headings": article.get("headings"),
            "bold_pairs": article.get("bold_pairs"),
            **title_features(title),
            "source_title": source_title,
            "source_match_type": match_type,
            "match_review_status": "confirmed" if match_type == "exact" else "needs_review" if match_type in {"same_date_fuzzy", "ambiguous"} else "unmatched",
            "title_similarity": round(similarity, 4),
            "source_evidence_level": evidence_level,
            "total_readers": total,
            "recommend_readers": recommend,
            "recommendation_dependency": round(float(recommend) / float(total), 6) if recommend is not None and total else None,
            "daily_shares_signal": day.get("shares"),
            "daily_favorites_signal": day.get("favorites"),
            "daily_published_articles": day.get("published_articles"),
            "known_source_rows": len(channel_map),
        }
        for source_name, field_name in CHANNEL_COLUMNS.items():
            if field_name not in record or record.get(field_name) is None:
                record[field_name] = channel_map.get(source_name)
        records.append(record)

    unmatched_source = []
    for key, rows in source_groups.items():
        if key not in used_keys:
            unmatched_source.append(
                {
                    "publish_date": key[0],
                    "source_title": rows[0].get("source_title"),
                    "channels": sorted({str(row.get("source_channel", "")) for row in rows}),
                }
            )
    coverage = defaultdict(int)
    for record in records:
        coverage[record["source_evidence_level"]] += 1
    return {
        "matching_version": "1.0",
        "article_count": len(records),
        "coverage": dict(sorted(coverage.items())),
        "records": records,
        "unmatched_source_articles": unmatched_source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Match canonical article files to normalized WeChat metrics.")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()
    result = match(load_json(args.inventory), load_json(args.metrics))
    write_json(args.output_json, result)
    write_csv(args.output_csv, FIELDS, result["records"])
    print(f"matched={len(result['records'])} coverage={result['coverage']}")


if __name__ == "__main__":
    main()
