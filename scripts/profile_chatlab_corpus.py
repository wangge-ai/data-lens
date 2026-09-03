from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from _common import file_sha256, guard_cli_output, load_json, write_json


CONTENT_TYPES = {0, 7, 25}
SYSTEM_TYPES = {80}
TYPE_LABELS = {
    0: "plain_text",
    4: "file_share",
    7: "rich_or_system_text",
    23: "location_or_transfer_23",
    24: "mini_program",
    25: "quoted_or_reply",
    27: "contact_card",
    80: "system_notice",
    99: "other_99",
}
QUESTION_RE = re.compile(r"[?？]|怎么|如何|为什么|为啥|有没有|能不能|请问|求助|谁知道")
RESOURCE_RE = re.compile(r"https?://|\[文件\]|github|skill|教程|文档|资料|脚本|代码|开源", re.I)
PRACTICE_RE = re.compile(r"测试|实测|报错|错误|失败|成功|安装|运行|部署|配置|复现|提示")
AI_RE = re.compile(r"\bai\b|codex|claude|deepseek|chatgpt|gpt|智能体|大模型|模型|prompt|提示词", re.I)
ECOM_RE = re.compile(r"电商|商品|主图|详情页|淘宝|天猫|京东|拼多多|店铺|销量|投放|广告")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True).strip()


def _timestamp(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _iso_time(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _message_key(message: dict[str, Any]) -> str:
    platform_id = str(message.get("platformMessageId") or "").strip()
    if platform_id:
        return f"platform:{platform_id}"
    return "fallback:" + hashlib.sha256(
        "|".join(
            [
                str(message.get("sender") or ""),
                str(message.get("timestamp") or ""),
                str(message.get("type") or ""),
                _as_text(message.get("content")),
            ]
        ).encode("utf-8")
    ).hexdigest()


def _conversation_key(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    members = payload.get("members") or []
    member_ids = sorted(
        str(item.get("platformId") or item.get("accountName") or "").strip()
        for item in members
        if isinstance(item, dict) and str(item.get("platformId") or item.get("accountName") or "").strip()
    )
    conversation_type = str(meta.get("type") or "unknown")
    message_senders = sorted(
        {
            str(item.get("sender") or "").strip()
            for item in payload.get("messages", [])
            if isinstance(item, dict) and str(item.get("sender") or "").strip()
        }
    )
    stable_target = str(meta.get("groupId") or meta.get("groupID") or meta.get("conversationId") or meta.get("chatId") or "")
    if not stable_target and conversation_type == "private" and message_senders:
        stable_target = "|".join(message_senders)
    if not stable_target:
        stable_target = "|".join(member_ids) or str(meta.get("name") or "unknown")
    return "|".join(
        [str(meta.get("platform") or "unknown"), conversation_type, stable_target]
    )


def _type_label(value: Any) -> str:
    try:
        message_type = int(value)
    except (TypeError, ValueError):
        return f"unknown_{value}"
    return TYPE_LABELS.get(message_type, f"unknown_{message_type}")


def _is_chatlab(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("meta"), dict)
        and isinstance(payload.get("members"), list)
        and isinstance(payload.get("messages"), list)
        and ("chatlab" in payload or str((payload.get("meta") or {}).get("platform") or "").lower() == "wechat")
    )


def discover_exports(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    candidates: list[Path] = []
    for supplied in paths:
        if supplied.is_file() and supplied.suffix.lower() == ".json":
            candidates.append(supplied)
        elif supplied.is_dir():
            candidates.extend(path for path in supplied.rglob("*.json") if path.is_file())
    exports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    ignored = 0
    for path in sorted(set(candidates), key=lambda item: str(item).lower()):
        try:
            payload = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append({"path": str(path.resolve()), "reason": "json_parse_error", "detail": str(exc)[:300]})
            continue
        if not _is_chatlab(payload):
            ignored += 1
            continue
        messages = [item for item in payload.get("messages", []) if isinstance(item, dict)]
        unique_count = len({_message_key(item) for item in messages})
        exports.append(
            {
                "path": path.resolve(),
                "sha256": file_sha256(path),
                "payload": payload,
                "conversation_key": _conversation_key(payload),
                "message_count": len(messages),
                "unique_message_count": unique_count,
                "size_bytes": path.stat().st_size,
            }
        )
    return exports, failures, ignored


def _cue_tags(content: str) -> list[str]:
    tags: list[str] = []
    if QUESTION_RE.search(content):
        tags.append("question_candidate")
    if len(content) >= 100:
        tags.append("long_form_candidate")
    if RESOURCE_RE.search(content):
        tags.append("resource_candidate")
    if PRACTICE_RE.search(content):
        tags.append("practice_candidate")
    if AI_RE.search(content):
        tags.append("ai_lexical_cue")
    if ECOM_RE.search(content):
        tags.append("ecommerce_lexical_cue")
    return tags


def _content_message(message: dict[str, Any]) -> bool:
    try:
        message_type = int(message.get("type"))
    except (TypeError, ValueError):
        return False
    return message_type in CONTENT_TYPES and len(_as_text(message.get("content"))) >= 4


def _sample_key(conversation_id: str, message: dict[str, Any]) -> str:
    return hashlib.sha256(f"{conversation_id}|{_message_key(message)}".encode("utf-8")).hexdigest()


def _bounded_text(value: str, maximum: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= maximum else (value[:maximum], True)


def _context(messages: list[dict[str, Any]], index: int, direction: int, maximum: int) -> dict[str, Any] | None:
    position = index + direction
    while 0 <= position < len(messages):
        candidate = messages[position]
        if _content_message(candidate):
            text, truncated = _bounded_text(_as_text(candidate.get("content")), maximum)
            return {
                "message_index": position,
                "timestamp": _iso_time(_timestamp(candidate.get("timestamp"))),
                "sender_label": str(candidate.get("accountName") or ""),
                "content": text,
                "truncated": truncated,
            }
        position += direction
    return None


def _review_samples(
    conversation_id: str,
    source: dict[str, Any],
    max_samples: int,
    max_content_chars: int,
) -> list[dict[str, Any]]:
    messages = [item for item in source["payload"].get("messages", []) if isinstance(item, dict)]
    eligible = [
        (index, item, _cue_tags(_as_text(item.get("content"))))
        for index, item in enumerate(messages)
        if _content_message(item)
    ]
    if not eligible or max_samples <= 0:
        return []
    per_stratum = max(1, max_samples // 3)
    strata: dict[str, list[tuple[int, dict[str, Any], list[str]]]] = defaultdict(list)
    for rank, row in enumerate(eligible):
        stratum_index = min(2, (rank * 3) // len(eligible))
        strata[("early", "middle", "late")[stratum_index]].append(row)
    chosen: list[tuple[str, int, dict[str, Any], list[str], str]] = []
    used: set[str] = set()
    priorities = ["question_candidate", "practice_candidate", "resource_candidate", "long_form_candidate", "general_candidate"]
    for stratum in ("early", "middle", "late"):
        pool = strata.get(stratum, [])
        for priority in priorities:
            if sum(1 for row in chosen if row[0] == stratum) >= per_stratum:
                break
            available = [
                row
                for row in pool
                if _message_key(row[1]) not in used and (priority == "general_candidate" or priority in row[2])
            ]
            if not available:
                continue
            index, message, tags = min(available, key=lambda row: _sample_key(conversation_id, row[1]))
            used.add(_message_key(message))
            chosen.append((stratum, index, message, tags, priority))
        while sum(1 for row in chosen if row[0] == stratum) < per_stratum:
            available = [row for row in pool if _message_key(row[1]) not in used]
            if not available:
                break
            index, message, tags = min(available, key=lambda row: _sample_key(conversation_id, row[1]))
            used.add(_message_key(message))
            chosen.append((stratum, index, message, tags, "general_candidate"))
    if len(chosen) < max_samples:
        remaining = [row for row in eligible if _message_key(row[1]) not in used]
        for index, message, tags in sorted(remaining, key=lambda row: _sample_key(conversation_id, row[1])):
            if len(chosen) >= max_samples:
                break
            stratum_index = min(2, (eligible.index((index, message, tags)) * 3) // len(eligible))
            stratum = ("early", "middle", "late")[stratum_index]
            used.add(_message_key(message))
            chosen.append((stratum, index, message, tags, "general_candidate"))
    output: list[dict[str, Any]] = []
    for stratum, index, message, tags, reason in sorted(chosen, key=lambda row: row[1]):
        content, truncated = _bounded_text(_as_text(message.get("content")), max_content_chars)
        output.append(
            {
                "sample_id": _stable_id("CHAT-SAMPLE", conversation_id, _message_key(message)),
                "conversation_id": conversation_id,
                "source_path": str(source["path"]),
                "source_sha256": source["sha256"],
                "message_index": index,
                "locator": {"type": "json_pointer", "pointer": f"/messages/{index}"},
                "platform_message_id": str(message.get("platformMessageId") or "") or None,
                "timestamp": _iso_time(_timestamp(message.get("timestamp"))),
                "sender_label": str(message.get("accountName") or ""),
                "message_type": int(message.get("type")),
                "message_type_label": TYPE_LABELS.get(int(message.get("type")), f"unknown_{message.get('type')}"),
                "time_stratum": stratum,
                "selection_reason": reason,
                "lexical_cues": tags,
                "content": content,
                "content_truncated": truncated,
                "context_before": _context(messages, index, -1, min(max_content_chars, 360)),
                "context_after": _context(messages, index, 1, min(max_content_chars, 360)),
                "review_status": "unreviewed_candidate",
            }
        )
    return output


def profile_chatlab(
    paths: Iterable[Path],
    inventory: dict[str, Any] | None = None,
    max_samples_per_conversation: int = 12,
    max_content_chars: int = 1200,
) -> dict[str, Any]:
    exports, failures, ignored = discover_exports(paths)
    inventory_ids = {
        str(Path(str(item.get("path") or "")).resolve()).lower(): str(item.get("source_container_id") or "")
        for item in (inventory or {}).get("files", [])
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for export in exports:
        grouped[export["conversation_key"]].append(export)
    canonical_exports: list[dict[str, Any]] = []
    variant_exports: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda row: (row["unique_message_count"], row["message_count"], row["size_bytes"], str(row["path"])),
            reverse=True,
        )
        canonical_exports.append(ordered[0])
        for row in ordered[1:]:
            variant_exports.append(
                {
                    "conversation_key": key,
                    "path": str(row["path"]),
                    "sha256": row["sha256"],
                    "message_count": row["message_count"],
                    "canonical_path": str(ordered[0]["path"]),
                    "reason": "same_conversation_key_lower_or_equal_message_coverage",
                }
            )

    conversations: list[dict[str, Any]] = []
    review_samples: list[dict[str, Any]] = []
    corpus_type_counts: Counter[str] = Counter()
    corpus_cues: Counter[str] = Counter()
    total_unique_messages = 0
    total_messages = 0
    all_timestamps: list[int] = []
    for source in sorted(canonical_exports, key=lambda row: str((row["payload"].get("meta") or {}).get("name") or "")):
        payload = source["payload"]
        meta = payload.get("meta") or {}
        messages = [item for item in payload.get("messages", []) if isinstance(item, dict)]
        conversation_id = _stable_id("CHAT", source["conversation_key"])
        message_keys = [_message_key(item) for item in messages]
        unique_messages = len(set(message_keys))
        timestamps = [stamp for item in messages if (stamp := _timestamp(item.get("timestamp"))) is not None]
        all_timestamps.extend(timestamps)
        type_label_counts = Counter(_type_label(item.get("type")) for item in messages)
        sender_counts = Counter(str(item.get("accountName") or "[missing]") for item in messages)
        eligible = [item for item in messages if _content_message(item)]
        cue_counts = Counter(tag for item in eligible for tag in _cue_tags(_as_text(item.get("content"))))
        char_lengths = [len(_as_text(item.get("content"))) for item in eligible]
        monthly_counts = Counter(
            datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m") for stamp in timestamps
        )
        active_days = {
            datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d") for stamp in timestamps
        }
        source_id = inventory_ids.get(str(source["path"]).lower()) or None
        samples = _review_samples(
            conversation_id,
            source,
            max_samples=max_samples_per_conversation,
            max_content_chars=max_content_chars,
        )
        review_samples.extend(samples)
        corpus_type_counts.update({label: count for label, count in type_label_counts.items()})
        corpus_cues.update(cue_counts)
        total_messages += len(messages)
        total_unique_messages += unique_messages
        conversations.append(
            {
                "conversation_id": conversation_id,
                "name": str(meta.get("name") or source["path"].stem),
                "conversation_type": str(meta.get("type") or "unknown"),
                "platform": str(meta.get("platform") or "unknown"),
                "source_container_id": source_id,
                "source_path": str(source["path"]),
                "source_sha256": source["sha256"],
                "member_count": len(payload.get("members") or []),
                "message_count": len(messages),
                "unique_message_count": unique_messages,
                "duplicate_message_count": len(messages) - unique_messages,
                "sender_count": len(sender_counts),
                "top_senders": [
                    {"sender_label": label, "message_count": count, "message_share": round(count / len(messages), 4) if messages else 0}
                    for label, count in sender_counts.most_common(8)
                ],
                "start_time": _iso_time(min(timestamps) if timestamps else None),
                "end_time": _iso_time(max(timestamps) if timestamps else None),
                "active_day_count": len(active_days),
                "monthly_message_counts": dict(sorted(monthly_counts.items())),
                "message_type_counts": dict(sorted(type_label_counts.items())),
                "semantic_candidate_count": len(eligible),
                "median_candidate_chars": statistics.median(char_lengths) if char_lengths else None,
                "lexical_cue_counts": dict(sorted(cue_counts.items())),
                "review_sample_count": len(samples),
            }
        )

    canonical_source_ids = [item["source_container_id"] for item in conversations if item.get("source_container_id")]
    conversation_type_aggregates: list[dict[str, Any]] = []
    for conversation_type in sorted({item["conversation_type"] for item in conversations}):
        rows = [item for item in conversations if item["conversation_type"] == conversation_type]
        message_total = sum(int(item["message_count"]) for item in rows)
        semantic_total = sum(int(item["semantic_candidate_count"]) for item in rows)
        message_types = Counter()
        cue_counts = Counter()
        for item in rows:
            message_types.update(item["message_type_counts"])
            cue_counts.update(item["lexical_cue_counts"])
        conversation_type_aggregates.append(
            {
                "conversation_type": conversation_type,
                "conversation_count": len(rows),
                "message_count": message_total,
                "semantic_candidate_count": semantic_total,
                "message_type_counts": dict(sorted(message_types.items())),
                "lexical_cue_counts": dict(sorted(cue_counts.items())),
                "derived_rates": {
                    "quoted_or_reply_share_of_messages": round(message_types.get("quoted_or_reply", 0) / message_total, 4) if message_total else None,
                    "question_cue_share_of_semantic_candidates": round(cue_counts.get("question_candidate", 0) / semantic_total, 4) if semantic_total else None,
                    "resource_cue_share_of_semantic_candidates": round(cue_counts.get("resource_candidate", 0) / semantic_total, 4) if semantic_total else None,
                    "practice_cue_share_of_semantic_candidates": round(cue_counts.get("practice_candidate", 0) / semantic_total, 4) if semantic_total else None,
                    "ai_cue_share_of_semantic_candidates": round(cue_counts.get("ai_lexical_cue", 0) / semantic_total, 4) if semantic_total else None,
                    "ecommerce_cue_share_of_semantic_candidates": round(cue_counts.get("ecommerce_lexical_cue", 0) / semantic_total, 4) if semantic_total else None,
                },
            }
        )
    return {
        "contract_version": "data-lens-chatlab-corpus-profile/0.1",
        "method": {
            "kind": "deterministic",
            "status": "experimental",
            "analysis_unit": "message_within_conversation",
            "deduplication_rule": "same platform/type/stable conversation target keeps export with greatest unique message coverage",
            "sampling_rule": "per-conversation early/middle/late strata with cue-balanced deterministic hash selection",
        },
        "summary": {
            "json_files_considered": len(exports) + ignored + len(failures),
            "recognized_chatlab_exports": len(exports),
            "ignored_non_chatlab_json": ignored,
            "failed_json_files": len(failures),
            "canonical_conversations": len(conversations),
            "variant_exports": len(variant_exports),
            "messages_in_canonical_exports": total_messages,
            "unique_messages_in_canonical_exports": total_unique_messages,
            "conversation_types": dict(Counter(item["conversation_type"] for item in conversations)),
            "message_type_counts": dict(sorted(corpus_type_counts.items())),
            "lexical_cue_counts": dict(sorted(corpus_cues.items())),
            "start_time": _iso_time(min(all_timestamps) if all_timestamps else None),
            "end_time": _iso_time(max(all_timestamps) if all_timestamps else None),
            "review_sample_count": len(review_samples),
        },
        "scope_support": {
            "canonical_source_container_ids": canonical_source_ids,
            "shared_object_candidate": "recognized ChatLab conversation exports",
            "attachments_are_auxiliary_until_linked": True,
            "runtime_directories_are_not_conversation_evidence": True,
        },
        "conversations": conversations,
        "conversation_type_aggregates": conversation_type_aggregates,
        "variant_exports": sorted(variant_exports, key=lambda item: item["path"]),
        "review_samples": review_samples,
        "failure_ledger": failures,
        "boundaries": [
            "Lexical cues select review candidates; they are not semantic themes or findings.",
            "Conversation messages are not independent observations when they belong to the same interaction chain.",
            "Attachments, images, audio, and video remain source-only until explicitly linked and reviewed in their own evidence lane.",
            "Sender labels and private-chat content are local sensitive data and must not be copied into public fixtures or releases.",
            "The host agent must review samples, propose angles, search counterexamples, and submit candidates to adoption ledgers.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile ChatLab/WeChat JSON exports and build bounded semantic review samples.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-samples-per-conversation", type=int, default=12)
    parser.add_argument("--max-content-chars", type=int, default=1200)
    args = parser.parse_args()
    if args.max_samples_per_conversation < 0 or args.max_samples_per_conversation > 30:
        raise SystemExit("--max-samples-per-conversation must be between 0 and 30")
    if args.max_content_chars < 80 or args.max_content_chars > 4000:
        raise SystemExit("--max-content-chars must be between 80 and 4000")
    guard_cli_output(parser, args.output, [*args.paths, *([args.inventory] if args.inventory else [])])
    result = profile_chatlab(
        args.paths,
        inventory=load_json(args.inventory) if args.inventory else None,
        max_samples_per_conversation=args.max_samples_per_conversation,
        max_content_chars=args.max_content_chars,
    )
    write_json(args.output, result)
    print(
        json.dumps(
            {"output": str(args.output.resolve()), **result["summary"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
