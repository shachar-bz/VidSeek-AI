"""Extracts the middle frame of a video as a web-ready JPEG thumbnail."""

from __future__ import annotations

import subprocess
from pathlib import Path

from backend.core.security import probe_media_duration_seconds


class ThumbnailGenerationError(RuntimeError):
    """The source video could not produce its required middle-frame thumbnail."""


def generate_middle_frame(
    video_path: Path,
    output_path: Path,
    *,
    duration_seconds: float | None = None,
) -> Path:
    """Write the frame at 50% of the video's measured duration to ``output_path``."""
    measured_duration = (
        duration_seconds
        if duration_seconds is not None
        else probe_media_duration_seconds(video_path)
    )
    if measured_duration is None or measured_duration <= 0:
        raise ThumbnailGenerationError("Video duration is unavailable")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-ss",
        f"{measured_duration / 2:.6f}",
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-2:force_original_aspect_ratio=decrease",
        "-q:v",
        "3",
        "-y",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ThumbnailGenerationError(
            "ffmpeg was not found on PATH; install FFmpeg to create video thumbnails"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        raise ThumbnailGenerationError(
            f"ffmpeg could not extract the middle frame: {detail or 'unknown error'}"
        ) from error

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ThumbnailGenerationError("ffmpeg did not create a thumbnail image")
    return output_path
