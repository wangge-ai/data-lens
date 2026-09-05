from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from _common import file_sha256, write_json
from video_evidence import probe_duration


METHOD_ID = "data_lens.local_whisper_transcription"
METHOD_VERSION = "0.2.0"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(runner: Runner, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _failure(stage: str, error: Exception | str) -> dict[str, Any]:
    if isinstance(error, Exception):
        error_type, message = type(error).__name__, str(error)
    else:
        error_type, message = "ProcessError", error
    return {
        "failure_id": f"clip-{stage}",
        "stage": stage,
        "error_type": error_type,
        "message": message[:1000],
        "retry_status": "not_retried",
    }


def clip_bounds(duration_ms: int, max_minutes: int, start_ms: int | None, end_ms: int | None) -> tuple[int, int]:
    maximum_ms = max_minutes * 60_000
    if (start_ms is None) != (end_ms is None):
        raise ValueError("start_ms and end_ms must be supplied together")
    if start_ms is None:
        if duration_ms > maximum_ms:
            raise ValueError(f"media exceeds the {max_minutes}-minute budget; supply explicit start_ms and end_ms")
        return 0, duration_ms
    assert end_ms is not None
    if start_ms < 0 or end_ms <= start_ms or end_ms > duration_ms:
        raise ValueError(f"clip bounds must satisfy 0 <= start_ms < end_ms <= {duration_ms}")
    if end_ms - start_ms > maximum_ms:
        raise ValueError(f"selected clip exceeds the {max_minutes}-minute budget")
    return start_ms, end_ms


def normalize_transcript(raw: dict[str, Any], offset_ms: int, clip_end_ms: int | None = None) -> dict[str, Any]:
    raw_segments = raw.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("Whisper JSON does not contain a segments list")
    segments: list[dict[str, Any]] = []
    invalid_word_count = 0
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise ValueError("Whisper segment must be an object")
        try:
            start_ms = offset_ms + round(float(segment["start"]) * 1000)
            end_ms = offset_ms + round(float(segment["end"]) * 1000)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Whisper segment is missing valid start/end timestamps") from exc
        if start_ms < offset_ms or end_ms <= start_ms or (clip_end_ms is not None and end_ms > clip_end_ms + 1000):
            raise ValueError("Whisper segment timestamp is outside the selected clip")
        words: list[dict[str, Any]] = []
        for word in segment.get("words") or []:
            if not isinstance(word, dict):
                invalid_word_count += 1
                continue
            try:
                word_start = offset_ms + round(float(word["start"]) * 1000)
                word_end = offset_ms + round(float(word["end"]) * 1000)
                if word_start < offset_ms or word_end <= word_start or word_start < start_ms - 1000 or word_end > end_ms + 1000 or (clip_end_ms is not None and word_end > clip_end_ms + 1000):
                    invalid_word_count += 1
                    continue
                words.append({"text": str(word.get("word") or ""), "start_ms": word_start, "end_ms": word_end, "probability": word.get("probability")})
            except (KeyError, TypeError, ValueError):
                invalid_word_count += 1
                continue
        segments.append(
            {
                "segment_index": index,
                "text": str(segment.get("text") or "").strip(),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "words": words,
                "quality": {
                    "avg_logprob": segment.get("avg_logprob"),
                    "compression_ratio": segment.get("compression_ratio"),
                    "no_speech_prob": segment.get("no_speech_prob"),
                },
            }
        )
    normalized_texts = [re.sub(r"\s+", "", segment["text"]).lower() for segment in segments if segment["text"]]
    repeated = sorted({text for text in normalized_texts if normalized_texts.count(text) > 1})
    flagged = [
        segment["segment_index"]
        for segment in segments
        if (isinstance(segment["quality"]["no_speech_prob"], (int, float)) and segment["quality"]["no_speech_prob"] >= 0.6)
        or (isinstance(segment["quality"]["avg_logprob"], (int, float)) and segment["quality"]["avg_logprob"] <= -1.0)
        or not segment["text"]
    ]
    review_sample = set(flagged[:3])
    if segments:
        review_sample.update((0, len(segments) // 2, len(segments) - 1))
    non_monotonic = sum(segments[index]["start_ms"] < segments[index - 1]["start_ms"] for index in range(1, len(segments)))
    return {
        "text": str(raw.get("text") or "").strip(),
        "language": raw.get("language"),
        "segments": segments,
        "quality_screen": {
            "segment_count": len(segments),
            "empty_segment_count": sum(not segment["text"] for segment in segments),
            "invalid_word_timestamp_count": invalid_word_count,
            "non_monotonic_segment_count": non_monotonic,
            "repeated_segment_texts": repeated[:10],
            "flagged_segment_indices": flagged,
            "review_sample_segment_indices": sorted(review_sample)[:6],
            "status": "review_required" if segments else "empty_or_no_speech_candidate",
        },
    }


def build_transcription_evidence(
    source: Path,
    output_dir: Path,
    *,
    model_checkpoint: Path,
    max_minutes: int = 20,
    start_ms: int | None = None,
    end_ms: int | None = None,
    language: str = "zh",
    task: str = "transcribe",
    device: str = "cpu",
    timeout: int = 1800,
    runner: Runner = subprocess.run,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    whisper: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    if not model_checkpoint.is_file():
        raise FileNotFoundError(f"local Whisper checkpoint is required: {model_checkpoint}")
    if max_minutes < 1 or max_minutes > 120:
        raise ValueError("max_minutes must be between 1 and 120")
    if task not in {"transcribe", "translate"}:
        raise ValueError("task must be transcribe or translate")
    if device not in {"cpu", "cuda"}:
        raise ValueError("device must be cpu or cuda")
    if not language or any(character.isspace() for character in language):
        raise ValueError("language must be one Whisper language code without spaces")
    if timeout < 1 or timeout > 7200:
        raise ValueError("timeout must be between 1 and 7200 seconds")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory must be empty: {output_dir}")
    ffmpeg_command = ffmpeg or shutil.which("ffmpeg")
    ffprobe_command = ffprobe or shutil.which("ffprobe")
    whisper_command = whisper or shutil.which("whisper")
    if not ffmpeg_command or not ffprobe_command or not whisper_command:
        raise RuntimeError("FFmpeg, ffprobe, and the local Whisper CLI must all be available")
    source_hash_before = file_sha256(source)
    model_hash = file_sha256(model_checkpoint)
    try:
        whisper_version = importlib.metadata.version("openai-whisper")
    except importlib.metadata.PackageNotFoundError:
        whisper_version = "unknown"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        duration_ms = probe_duration(source, runner=runner, executable=ffprobe_command, timeout=min(timeout, 300))
    except Exception as exc:
        stage = "duration_probe_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "duration_probe"
        failure = _failure(stage, exc)
        result = {
            "source_path": str(source.resolve()),
            "source_sha256": source_hash_before,
            "source_unchanged": source_hash_before == file_sha256(source),
            "source_duration_ms": None,
            "clip_locator": None,
            "clip_path": None,
            "clip_sha256": None,
            "model_checkpoint_sha256": model_hash,
            "model_checkpoint_source": "explicit_local_path",
            "whisper_package_version": whisper_version,
            "network_download_requested": False,
            "completion_status": "failed",
            "speaker_review_status": "not_reviewed",
            "semantic_review_status": "not_reviewed",
            "adoption_status": "not_adopted",
            "transcript": None,
            "failure_ledger": [failure],
            "recovery": {"automatic_retry": False, "resume_supported": False, "next_attempt_requires": "new_empty_output_directory"},
        }
        payload = {
            "contract_version": "data-lens-method-result/1.0",
            "method_id": METHOD_ID,
            "method_version": METHOD_VERSION,
            "status": "failed",
            "results": [result],
            "diagnostics": [{"failure_count": 1}, {"failed_stage": stage}],
            "boundaries": ["The timed-out command was not retried automatically; use a new empty output directory for an explicit retry."],
        }
        write_json(output_dir / "transcription-evidence.json", payload)
        return payload
    try:
        clip_start, clip_end = clip_bounds(duration_ms, max_minutes, start_ms, end_ms)
    except ValueError as exc:
        failure = _failure("clip_eligibility", exc)
        result = {
            "source_path": str(source.resolve()),
            "source_sha256": source_hash_before,
            "source_unchanged": source_hash_before == file_sha256(source),
            "source_duration_ms": duration_ms,
            "clip_locator": None,
            "clip_path": None,
            "clip_sha256": None,
            "model_checkpoint_sha256": model_hash,
            "model_checkpoint_source": "explicit_local_path",
            "whisper_package_version": whisper_version,
            "network_download_requested": False,
            "completion_status": "ineligible",
            "speaker_review_status": "not_reviewed",
            "semantic_review_status": "not_reviewed",
            "adoption_status": "not_adopted",
            "transcript": None,
            "failure_ledger": [failure],
            "recovery": {"automatic_retry": False, "resume_supported": False, "next_attempt_requires": "explicit_bounded_clip_and_new_empty_output_directory"},
        }
        payload = {
            "contract_version": "data-lens-method-result/1.0",
            "method_id": METHOD_ID,
            "method_version": METHOD_VERSION,
            "status": "ineligible",
            "results": [result],
            "diagnostics": [{"duration_ms": duration_ms}, {"failed_stage": "clip_eligibility"}],
            "boundaries": ["No transcription ran because the requested clip exceeded or violated the declared bound."],
        }
        write_json(output_dir / "transcription-evidence.json", payload)
        return payload
    clip_path = output_dir / "bounded-clip.wav"
    raw_dir = output_dir / "whisper-raw"
    raw_dir.mkdir()
    failures: list[dict[str, Any]] = []
    normalized: dict[str, Any] | None = None
    try:
        clip_completed = _run(
            runner,
            [
                ffmpeg_command,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{clip_start / 1000:.3f}",
                "-t",
                f"{(clip_end - clip_start) / 1000:.3f}",
                "-i",
                str(source.resolve()),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-n",
                str(clip_path.resolve()),
            ],
            min(timeout, 300),
        )
    except subprocess.TimeoutExpired as exc:
        clip_completed = None
        failures.append(_failure("audio_extraction_timeout", exc))
    if clip_completed is None:
        pass
    elif clip_completed.returncode or not clip_path.is_file():
        message = (clip_completed.stderr or clip_completed.stdout).strip() or "ffmpeg did not create the bounded audio clip"
        failures.append(_failure("audio_extraction", message))
    else:
        command = [
            whisper_command,
            str(clip_path.resolve()),
            "--model",
            str(model_checkpoint.resolve()),
            "--language",
            language,
            "--task",
            task,
            "--output_dir",
            str(raw_dir.resolve()),
            "--output_format",
            "json",
            "--word_timestamps",
            "True",
            "--verbose",
            "False",
            "--device",
            device,
        ]
        if device == "cpu":
            command.extend(["--fp16", "False"])
        try:
            completed = _run(runner, command, timeout)
        except subprocess.TimeoutExpired as exc:
            completed = None
            failures.append(_failure("transcription_timeout", exc))
        raw_path = raw_dir / "bounded-clip.json"
        if completed is None:
            pass
        elif completed.returncode or not raw_path.is_file():
            message = (completed.stderr or completed.stdout).strip() or "Whisper did not create the expected JSON"
            failures.append(_failure("transcription", message))
        else:
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                normalized = normalize_transcript(raw, clip_start, clip_end)
                normalized["raw_output_path"] = str(raw_path.resolve())
                normalized["raw_output_sha256"] = file_sha256(raw_path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                failures.append(_failure("transcript_normalization", exc))
    source_unchanged = source_hash_before == file_sha256(source)
    if not source_unchanged:
        failures.append(_failure("source_integrity", "source media hash changed during processing"))
    completion = "complete" if normalized is not None and normalized["segments"] and not failures else "complete_empty" if normalized is not None and not failures else "failed"
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": source_hash_before,
        "source_unchanged": source_unchanged,
        "source_duration_ms": duration_ms,
        "clip_locator": {"source_sha256": source_hash_before, "start_ms": clip_start, "end_ms": clip_end},
        "clip_path": str(clip_path.resolve()) if clip_path.is_file() else None,
        "clip_sha256": file_sha256(clip_path) if clip_path.is_file() else None,
        "model_checkpoint_sha256": model_hash,
        "model_checkpoint_source": "explicit_local_path",
        "whisper_package_version": whisper_version,
        "network_download_requested": False,
        "completion_status": completion,
        "speaker_review_status": "not_reviewed",
        "semantic_review_status": "not_reviewed",
        "adoption_status": "not_adopted",
        "transcript": normalized,
        "failure_ledger": failures,
        "recovery": None if not failures else {"automatic_retry": False, "resume_supported": False, "next_attempt_requires": "new_empty_output_directory"},
    }
    payload = {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "status": "succeeded" if completion in {"complete", "complete_empty"} else "failed",
        "results": [result],
        "diagnostics": [{"duration_ms": duration_ms}, {"clip_duration_ms": clip_end - clip_start}, {"failure_count": len(failures)}],
        "boundaries": [
            "The transcript is a local model candidate with time locators, not speaker review, semantic review, or an adopted finding.",
            "Only an explicit local checkpoint path is accepted; the adapter does not request a model download or retry with another model.",
            "Dialect, noise, overlapping speakers, repeated text, and no-speech segments require sampled playback review; this adapter does not perform diarization.",
        ],
    }
    write_json(output_dir / "transcription-evidence.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a bounded audio/video clip with an explicit local Whisper checkpoint and retain timestamp evidence.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-checkpoint", type=Path, required=True, help="Existing local checkpoint path; model names are not accepted")
    parser.add_argument("--max-minutes", type=int, default=20)
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--end-ms", type=int)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--task", choices=("transcribe", "translate"), default="transcribe")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    payload = build_transcription_evidence(
        args.source,
        args.output_dir,
        model_checkpoint=args.model_checkpoint,
        max_minutes=args.max_minutes,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        language=args.language,
        task=args.task,
        device=args.device,
        timeout=args.timeout,
    )
    result = payload["results"][0]
    print(json.dumps({"output": str((args.output_dir / "transcription-evidence.json").resolve()), "status": payload["status"], "clip_locator": result["clip_locator"], "failure_count": len(result["failure_ledger"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
