"""Decodes chosen frames of a local video at full resolution, for reading the text on them.

The sampling pass (`frame_stream.py`) shrinks every frame to 384 px, which is plenty for SigLIP
and the perceptual hash and far too small to read a slide. Keyframes are few -- one per segment
and one a minute in long ones -- so each is decoded again from the local file by a seek of its
own, at the video's own resolution. That resolution is only ever reduced, to at most
`KEYFRAME_LONG_SIDE`: enlarging adds no detail for OCR to read.

`-ss` before `-i` is an input seek: ffmpeg jumps to the keyframe before the time and decodes
forward to it. The frame comes back as a BMP, lossless, and is never written to disk.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from PIL import Image

from .frame_stream import FrameSamplingError

# Surya reads best at no more than 2048 px wide; a 1080p frame is under it and kept as is.
KEYFRAME_LONG_SIDE = 2048

# A seek into a local file takes well under a second; this only stops a broken file from
# holding indexing up.
KEYFRAME_DECODE_TIMEOUT_SECONDS = 60.0

# What ffmpeg says when the seek landed past the last frame: nothing to encode, so no output.
# Not a broken video, just no frame. `services/video_frames/extraction.py` makes the same
# call at query time; this package does not import that one, which is query-time only.
NO_FRAME_MARKERS = ("received no packets", "Nothing was written")


def decode_frame_at(
    video_path: Path, time_seconds: float, *, long_side: int = KEYFRAME_LONG_SIDE
) -> Image.Image | None:
    """The frame at `time_seconds`, at most `long_side` on its long side; None past the last frame.

    Raises `FrameSamplingError` when ffmpeg is missing, fails, or takes too long.
    """
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{max(time_seconds, 0.0):.3f}",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "bmp",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=KEYFRAME_DECODE_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError as error:
        raise FrameSamplingError(
            "ffmpeg was not found on PATH; install FFmpeg to index videos visually"
        ) from error
    except subprocess.TimeoutExpired:
        raise FrameSamplingError(
            f"Decoding the frame at {time_seconds:.1f} s of {video_path.name} took longer than "
            f"{KEYFRAME_DECODE_TIMEOUT_SECONDS:g} s"
        ) from None
    detail = completed.stderr.decode("utf-8", errors="replace").strip()
    if not completed.stdout and (
        completed.returncode == 0 or any(marker in detail for marker in NO_FRAME_MARKERS)
    ):
        return None
    if completed.returncode != 0:
        raise FrameSamplingError(
            f"ffmpeg could not decode the frame at {time_seconds:.1f} s of {video_path.name}: "
            f"{detail or f'exit code {completed.returncode}'}"
        )
    image = Image.open(io.BytesIO(completed.stdout))
    image.load()
    image = image.convert("RGB")
    # `thumbnail` only ever shrinks, and keeps the aspect ratio.
    image.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
    return image
