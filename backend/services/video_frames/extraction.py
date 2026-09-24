"""Extracts single frames from a video at given times, as small JPEGs (or PNGs for OCR), with ffmpeg.

No frame is ever stored, so every frame the visual sub-agent looks at is extracted here, on
demand. `source` is whatever ffmpeg can open: at query time a read-only SAS URL of the blob
(`source.py`), which ffmpeg seeks with HTTP range requests; in a test, a local file.

`-ss` goes before `-i`, which makes it an input seek: ffmpeg jumps to the nearest keyframe
before the time and decodes forward to it, instead of decoding the video from the start. The
frames of one call are extracted in parallel, one ffmpeg process each.

A SAS URL is a credential for the blob. It never appears in a log line or an exception here:
ffmpeg repeats its input in its error messages -- and its host alone in a DNS error -- so every
message is scrubbed of both first.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

# The long side of an extracted frame: enough to read a slide, small enough that one frame
# is one cheap image for a VLM.
FRAME_LONG_SIDE = 512

# ffmpeg's MJPEG quality scale, 2 (best) to 31 (worst).
JPEG_QUALITY = 4

# The long side a frame is read at for OCR, the same cap indexing reads keyframes at: a
# 512 px frame is too small to read, and enlarging adds no detail.
READABLE_LONG_SIDE = 2048

JPEG = "image/jpeg"
PNG = "image/png"

# How many frames one call extracts at once.
MAX_PARALLEL_EXTRACTIONS = 6

# A seek over HTTP into a video with no seek index can be slow; one frame taking longer than
# this is treated as a failure rather than holding an answer up indefinitely.
EXTRACTION_TIMEOUT_SECONDS = 30.0

# Anything that looks like a URL, so a message naming some other URL than `source` -- a
# redirect target, say -- is scrubbed as well.
URL_PATTERN = re.compile(r"https?://\S+")
SCRUBBED = "<video>"

# What ffmpeg says when the seek landed past the last frame: there was nothing to encode, so
# the encoder never opened and the output stayed empty. Not a broken video, just no frame.
NO_FRAME_MARKERS = ("received no packets", "Nothing was written")

logger = logging.getLogger(__name__)


class FrameExtractionError(RuntimeError):
    """ffmpeg could not produce a frame at the requested time."""


@dataclass(frozen=True)
class ExtractedFrame:
    """One frame as an image file, and the time it was taken at."""

    time_seconds: float
    # A JPEG unless the frame was asked for losslessly, then a PNG; `media_type` says which.
    image_bytes: bytes
    media_type: str = JPEG


def extract_frame(
    source: str,
    time_seconds: float,
    *,
    long_side: int = FRAME_LONG_SIDE,
    timeout_seconds: float = EXTRACTION_TIMEOUT_SECONDS,
    lossless: bool = False,
) -> ExtractedFrame:
    """The frame shown at `time_seconds`, shrunk so its long side is at most `long_side`.

    A frame already smaller than that is left at its own size. `lossless` returns a PNG
    rather than a JPEG, for OCR: a JPEG's ringing around thin strokes is what OCR misreads.
    """
    encoding = ["-c:v", "png"] if lossless else ["-c:v", "mjpeg", "-q:v", str(JPEG_QUALITY)]
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{max(time_seconds, 0.0):.3f}",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-vf",
        f"scale='min(iw,{long_side})':'min(ih,{long_side})':force_original_aspect_ratio=decrease",
        "-f",
        "image2pipe",
        *encoding,
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout_seconds, check=False
        )
    except FileNotFoundError as error:
        raise FrameExtractionError(
            "ffmpeg was not found on PATH; install FFmpeg to extract video frames"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise FrameExtractionError(
            f"Extracting the frame at {time_seconds:.1f} s took longer than "
            f"{timeout_seconds:g} s"
        ) from None
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if not completed.stdout and (
        completed.returncode == 0 or any(marker in stderr for marker in NO_FRAME_MARKERS)
    ):
        raise FrameExtractionError(f"The video has no frame at {time_seconds:.1f} s")
    if completed.returncode != 0:
        detail = scrub(stderr, source)
        raise FrameExtractionError(
            f"ffmpeg could not extract the frame at {time_seconds:.1f} s: "
            f"{detail or f'exit code {completed.returncode}'}"
        )
    return ExtractedFrame(
        time_seconds=time_seconds, image_bytes=completed.stdout, media_type=PNG if lossless else JPEG
    )


def extract_frames(
    source: str,
    times: Sequence[float],
    *,
    long_side: int = FRAME_LONG_SIDE,
    max_parallel: int = MAX_PARALLEL_EXTRACTIONS,
    lossless: bool = False,
) -> list[ExtractedFrame]:
    """The frames at every time in `times`, in the same order, extracted in parallel.

    One frame that cannot be extracted fails the call: the caller asked for exactly these
    moments, and quietly returning fewer images than times would leave it matching the wrong
    picture to the wrong time.
    """
    if not times:
        return []
    with ThreadPoolExecutor(
        max_workers=min(max_parallel, len(times)), thread_name_prefix="vidseek-frame"
    ) as pool:
        return list(
            pool.map(
                lambda time_seconds: extract_frame(
                    source, time_seconds, long_side=long_side, lossless=lossless
                ),
                times,
            )
        )


def scrub(message: str, source: str) -> str:
    """`message` with `source`, its host, and anything else URL-shaped taken out of it."""
    scrubbed = URL_PATTERN.sub(SCRUBBED, message.replace(source, SCRUBBED))
    host = urlsplit(source).hostname if "://" in source else None
    if host:
        scrubbed = scrubbed.replace(host, SCRUBBED)
    return scrubbed.strip()
