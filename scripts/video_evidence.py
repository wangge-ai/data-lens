from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from _common import file_sha256, write_json
from multimodal_inventory import image_size


METHOD_ID = "data_lens.video_frame_evidence"
METHOD_VERSION = "0.1.0"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def parse_duration_ms(text: str) -> int:
    try:
        payload = json.loads(text)
        duration = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("ffprobe output does not contain a valid positive format duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("ffprobe output does not contain a valid positive format duration")
    return max(1, round(duration * 1000))


def evenly_spaced_timestamps(duration_ms: int, maximum: int) -> list[int]:
    if duration_ms < 1:
        raise ValueError("duration must be positive")
    if maximum < 1:
        raise ValueError("maximum frame count must be positive")
    timestamps = {min(duration_ms - 1, max(0, round((index + 1) * duration_ms / (maximum + 1)))) for index in range(maximum)}
    return sorted(timestamps)


def parse_timestamp_spec(spec: str, duration_ms: int, maximum: int) -> list[int]:
    timestamps: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            raise ValueError("empty timestamp token")
        try:
            milliseconds = round(float(token) * 1000)
        except ValueError as exc:
            raise ValueError(f"invalid timestamp in seconds: {token}") from exc
        timestamps.add(milliseconds)
    selected = sorted(timestamps)
    if not selected or selected[0] < 0 or selected[-1] >= duration_ms:
        raise ValueError(f"timestamps must be at least 0 and before {duration_ms / 1000:.3f} seconds")
    if len(selected) > maximum:
        raise ValueError(f"selected {len(selected)} timestamps; maximum is {maximum}")
    return selected


def _run(runner: Runner, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _failure(timestamp_ms: int | None, stage: str, error: Exception | str) -> dict[str, Any]:
    if isinstance(error, Exception):
        error_type, message = type(error).__name__, str(error)
    else:
        error_type, message = "ProcessError", error
    unit = f"timestamp-{timestamp_ms}" if timestamp_ms is not None else "media"
    return {
        "failure_id": f"{unit}-{stage}",
        "timestamp_ms": timestamp_ms,
        "stage": stage,
        "error_type": error_type,
        "message": message[:1000],
        "retry_status": "not_retried",
    }


def probe_duration(source: Path, *, runner: Runner, executable: str, timeout: int) -> int:
    completed = _run(
        runner,
        [executable, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source.resolve())],
        timeout,
    )
    if completed.returncode:
        raise RuntimeError(f"ffprobe failed: {(completed.stderr or completed.stdout).strip()[:1000]}")
    return parse_duration_ms(completed.stdout)


def build_video_evidence(
    source: Path,
    output_dir: Path,
    *,
    max_frames: int = 6,
    timestamp_spec: str | None = None,
    max_width: int = 1600,
    timeout: int = 60,
    runner: Runner = subprocess.run,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    if max_frames < 1 or max_frames > 30:
        raise ValueError("max_frames must be between 1 and 30")
    if max_width < 320 or max_width > 4096:
        raise ValueError("max_width must be between 320 and 4096")
    if timeout < 1 or timeout > 300:
        raise ValueError("timeout must be between 1 and 300 seconds per frame")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory must be empty: {output_dir}")
    ffmpeg_command = ffmpeg or shutil.which("ffmpeg")
    ffprobe_command = ffprobe or shutil.which("ffprobe")
    if not ffmpeg_command or not ffprobe_command:
        raise RuntimeError("FFmpeg and ffprobe must both be available")
    source_hash_before = file_sha256(source)
    duration_ms = probe_duration(source, runner=runner, executable=ffprobe_command, timeout=timeout)
    selected = parse_timestamp_spec(timestamp_spec, duration_ms, max_frames) if timestamp_spec else evenly_spaced_timestamps(duration_ms, max_frames)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, timestamp_ms in enumerate(selected, start=1):
        frame_path = output_dir / f"frame-{index:04d}-at-{timestamp_ms:010d}ms.png"
        record: dict[str, Any] = {
            "timestamp_ms": timestamp_ms,
            "source_locator": {"source_sha256": source_hash_before, "timestamp_ms": timestamp_ms},
            "extraction_status": "pending",
            "semantic_review_status": "not_reviewed",
        }
        completed = _run(
            runner,
            [
                ffmpeg_command,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp_ms / 1000:.3f}",
                "-i",
                str(source.resolve()),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({max_width},iw)':-2",
                "-n",
                str(frame_path.resolve()),
            ],
            timeout,
        )
        if completed.returncode or not frame_path.is_file():
            message = (completed.stderr or completed.stdout).strip() or "ffmpeg did not create the expected frame"
            record["extraction_status"] = "failed"
            failures.append(_failure(timestamp_ms, "frame_extraction", message))
        else:
            dimensions = image_size(frame_path)
            record.update(
                {
                    "extraction_status": "succeeded",
                    "frame_path": str(frame_path.resolve()),
                    "frame_sha256": file_sha256(frame_path),
                    "frame_dimensions": list(dimensions) if dimensions else None,
                }
            )
        frames.append(record)
    source_unchanged = source_hash_before == file_sha256(source)
    if not source_unchanged:
        failures.append(_failure(None, "source_integrity", "source media hash changed during processing"))
    successful = sum(frame["extraction_status"] == "succeeded" for frame in frames)
    completion = "complete" if successful == len(selected) and not failures else "partial" if successful else "failed"
    result = {
        "source_path": str(source.resolve()),
        "source_sha256": source_hash_before,
        "source_unchanged": source_unchanged,
        "duration_ms": duration_ms,
        "selected_timestamps_ms": selected,
        "selection_strategy": "explicit_timestamps" if timestamp_spec else "evenly_spaced_bounded_sample",
        "max_frames": max_frames,
        "completion_status": completion,
        "semantic_review_status": "not_reviewed",
        "frames": frames,
        "failure_ledger": failures,
        "summary": {"selected": len(selected), "successful": successful, "failed": len(selected) - successful, "failure_count": len(failures)},
    }
    payload = {
        "contract_version": "data-lens-method-result/1.0",
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "status": "succeeded" if completion == "complete" else "failed",
        "results": [result],
        "diagnostics": [{"duration_ms": duration_ms}, {"failure_count": len(failures)}],
        "boundaries": [
            "Extracted frames are locatable preparation artifacts, not semantic review or adopted findings.",
            "Bounded timestamps do not establish full-video coverage; failures are retained without automatic retry.",
        ],
    }
    write_json(output_dir / "video-evidence.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract bounded video frames with timestamp/hash locators and a non-retried failure ledger.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=6)
    parser.add_argument("--timestamps", dest="timestamp_spec", help="Explicit timestamps in seconds, for example 0.5,10,42.25")
    parser.add_argument("--max-width", type=int, default=1600)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    payload = build_video_evidence(
        args.source,
        args.output_dir,
        max_frames=args.max_frames,
        timestamp_spec=args.timestamp_spec,
        max_width=args.max_width,
        timeout=args.timeout,
    )
    result = payload["results"][0]
    print(json.dumps({"output": str((args.output_dir / "video-evidence.json").resolve()), "status": payload["status"], **result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
