from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def plan_fallbacks(
    sample: dict[str, Any],
    extracts: dict[str, Any] | None = None,
    content_claims_required: bool = False,
    max_pdf_pages: int = 30,
    max_video_minutes: int = 20,
    max_images: int = 40,
) -> dict[str, Any]:
    extract_by_source = {
        str(item.get("source_container_id")): item
        for item in (extracts or {}).get("records", [])
    }
    actions: list[dict[str, Any]] = []
    for item in sample.get("selected", []):
        source_id = str(item.get("source_container_id") or "")
        path = Path(str(item.get("path") or ""))
        suffix = path.suffix.lower()
        extract = extract_by_source.get(source_id, {})
        empty_text = extract.get("status") in {"empty_requires_lane_specific_review", "origin_missing"} or (
            extract and int(extract.get("stored_char_count") or 0) == 0
        )
        action = "not_required"
        reason = "当前已有可定位文本，且用户问题不要求额外视觉或音视频证据。"
        evidence_needed: list[str] = []
        guardrail: dict[str, Any] = {}
        priority = "low"

        if suffix == ".pdf" and empty_text:
            action = "render_pages_then_ocr"
            reason = "PDF 文本抽取为空，不能据此补写内容。先渲染代表页，再按需 OCR。"
            evidence_needed = ["pdf_pages", "ocr_text"]
            guardrail = {"max_pages": max_pdf_pages, "expand_only_if_decision_relevant": True}
            priority = "high"
        elif suffix in IMAGE_EXTENSIONS:
            action = "ocr_then_semantic_review" if content_claims_required else "semantic_visual_review"
            reason = "图片需要语义审阅；只有当结论依赖图中文字时才追加 OCR。"
            evidence_needed = ["ocr_text", "image_region"] if content_claims_required else ["image_region"]
            guardrail = {"max_images_per_family": max_images, "sample_by_role": True}
            priority = "high" if content_claims_required else "medium"
        elif suffix in VIDEO_EXTENSIONS:
            action = "keyframes_and_transcript" if content_claims_required else "representative_keyframes"
            reason = "视频内容结论需要时间戳证据；涉及讲述内容时同时需要转录。"
            evidence_needed = ["video_frames", "transcript_segments"] if content_claims_required else ["video_frames"]
            guardrail = {"max_minutes_per_source": max_video_minutes, "expand_after_pilot": True}
            priority = "high"
        elif suffix in AUDIO_EXTENSIONS:
            action = "transcribe_audio"
            reason = "音频不能仅凭文件名支持内容结论。"
            evidence_needed = ["transcript_segments"]
            guardrail = {"max_minutes_per_source": max_video_minutes, "expand_after_pilot": True}
            priority = "high"
        elif suffix in {".pptx", ".docx"} and empty_text:
            action = "render_pages_then_ocr"
            reason = "办公文档文本抽取为空，先渲染页面，再决定是否 OCR。"
            evidence_needed = ["rendered_pages", "ocr_text"]
            guardrail = {"max_pages": max_pdf_pages, "expand_only_if_decision_relevant": True}
            priority = "high"
        elif empty_text:
            action = "manual_format_review"
            reason = "当前格式没有可定位文本抽取，必须选择专用解析器或明确排除。"
            evidence_needed = ["format_specific_locator"]
            guardrail = {"pilot_first": True}
            priority = "medium"

        actions.append({
            "source_container_id": source_id,
            "origin_path": str(path),
            "extension": suffix,
            "current_extract_status": extract.get("status") or "not_extracted",
            "recommended_action": action,
            "priority": priority,
            "reason": reason,
            "required_evidence": evidence_needed,
            "guardrail": guardrail,
            "review_status": "not_required" if action == "not_required" else "pending",
        })

    pending = [item for item in actions if item["review_status"] == "pending"]
    return {
        "multimodal_fallback_plan_version": "1.0",
        "content_claims_required": content_claims_required,
        "coverage_boundary": "该文件只生成降级处理计划，不证明 OCR、转录、抽帧或语义审阅已经完成。",
        "summary": {"selected": len(actions), "pending_fallbacks": len(pending), "not_required": len(actions) - len(pending)},
        "actions": actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan bounded OCR, page-render, frame, and transcript fallbacks for selected sources.")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--extract-manifest", type=Path)
    parser.add_argument("--content-claims-required", action="store_true")
    parser.add_argument("--max-pdf-pages", type=int, default=30)
    parser.add_argument("--max-video-minutes", type=int, default=20)
    parser.add_argument("--max-images", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = plan_fallbacks(
        load_json(args.sample), load_json(args.extract_manifest) if args.extract_manifest else None,
        args.content_claims_required, args.max_pdf_pages, args.max_video_minutes, args.max_images,
    )
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), **result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
