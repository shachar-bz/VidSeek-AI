"""Samples one frame every two seconds out of a local video file, in one ffmpeg decode pass.

This is the only time indexing decodes the video. ffmpeg picks the frames (`fps`), shrinks
them (`scale`) and writes each one to its stdout as a BMP, which is read back one image at a
time and handed to the caller. BMP because every frame carries its own size in its header, so
the stream can be split without knowing the output dimensions in advance -- ffmpeg applies a
video's rotation before scaling, and predicting the result from ffprobe's numbers is exactly
the kind of arithmetic that goes wrong on a phone video.

Nothing is written to disk. A frame lives as long as the caller keeps it, which during
indexing is one embedding batch.
"""

from __future__ import annotations

import io
import logging
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# One frame every two seconds: ~1,800 frames for an hour of video. What happens for less than
# about two seconds can fall between samples; the visual sub-agent refines around a hit by
# extracting the frames it needs.
SAMPLE_INTERVAL_SECONDS = 2.0

# The long side of a sampled frame. SigLIP 2 base looks at 256 px anyway, and the perceptual
# hash at 32 px, so decoding larger would only cost time.
SAMPLE_LONG_SIDE = 384

# The fixed 14-byte BMP file header: "BM", then the whole file's size as a little-endian
# uint32 at offset 2.
BMP_HEADER_BYTES = 14
BMP_SIGNATURE = b"BM"

# How much of ffmpeg's stderr is kept to explain a failure. It is drained continuously, so a
# video full of decode warnings cannot fill the pipe and stall the decode.
STDERR_TAIL_BYTES = 4096

logger = logging.getLogger(__name__)


class FrameSamplingError(RuntimeError):
    """ffmpeg could not decode the video, or is not installed."""


class SamplingStopped(RuntimeError):
    """The caller asked sampling to stop before the video was finished."""


@dataclass(frozen=True)
class SampledFrame:
    """One sampled frame and where in the video it was taken."""

    time_seconds: float
    image: Image.Image


def sample_frames(
    video_path: Path,
    *,
    interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    long_side: int = SAMPLE_LONG_SIDE,
    stop_event: threading.Event | None = None,
) -> Iterator[SampledFrame]:
    """Yield the video's frames at one per `interval_seconds`, in order, shrunk to `long_side`.

    The n-th frame is stamped `n * interval_seconds`: the `fps` filter emits one frame per
    tick of its output clock, choosing the input frame nearest each tick.

    Raises `SamplingStopped` when `stop_event` is set between two frames, and
    `FrameSamplingError` when ffmpeg is missing or exits with an error -- including for a
    file with no video stream, which acquisition already refuses to store.
    """
    command = _ffmpeg_command(video_path, interval_seconds=interval_seconds, long_side=long_side)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise FrameSamplingError(
            "ffmpeg was not found on PATH; install FFmpeg to index videos visually"
        ) from error

    stderr_tail = bytearray()
    drain = threading.Thread(
        target=_drain, args=(process.stderr, stderr_tail), name="ffmpeg-stderr", daemon=True
    )
    drain.start()
    finished = False
    try:
        index = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                raise SamplingStopped("Frame sampling was stopped")
            image = _read_bmp(process.stdout)
            if image is None:
                break
            yield SampledFrame(time_seconds=index * interval_seconds, image=image)
            index += 1
        finished = True
    finally:
        if not finished:
            process.kill()
        process.stdout.close()
        return_code = process.wait()
        drain.join(timeout=5)
    if return_code != 0:
        detail = bytes(stderr_tail).decode("utf-8", errors="replace").strip()
        raise FrameSamplingError(
            f"ffmpeg could not sample {video_path.name}: {detail or f'exit code {return_code}'}"
        )


def _ffmpeg_command(video_path: Path, *, interval_seconds: float, long_side: int) -> list[str]:
    """Decode the first video stream only, sample it, shrink it, write BMPs to stdout.

    `force_original_aspect_ratio=decrease` fits the frame inside a `long_side` square, which
    is "long side = `long_side`" for any shape without a conditional expression.
    """
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        (
            f"fps=1/{interval_seconds:g},"
            f"scale={long_side}:{long_side}:force_original_aspect_ratio=decrease"
        ),
        "-f",
        "image2pipe",
        "-c:v",
        "bmp",
        "pipe:1",
    ]


def _read_bmp(stream) -> Image.Image | None:
    """Read the next BMP off the stream, or None at a clean end of the stream."""
    header = _read_exactly(stream, BMP_HEADER_BYTES)
    if not header:
        return None
    if len(header) < BMP_HEADER_BYTES or header[:2] != BMP_SIGNATURE:
        raise FrameSamplingError("ffmpeg wrote something other than a BMP frame")
    size = int.from_bytes(header[2:6], "little")
    body = _read_exactly(stream, size - BMP_HEADER_BYTES)
    if len(body) < size - BMP_HEADER_BYTES:
        raise FrameSamplingError("ffmpeg's output ended in the middle of a frame")
    image = Image.open(io.BytesIO(header + body))
    # Decoded now, while the bytes are still referenced; the image outlives them otherwise.
    image.load()
    return image.convert("RGB")


def _read_exactly(stream, count: int) -> bytes:
    """Up to `count` bytes, fewer only at the end of the stream."""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _drain(stream, tail: bytearray) -> None:
    """Read a stream to its end, keeping only the last `STDERR_TAIL_BYTES` of it."""
    for line in iter(stream.readline, b""):
        tail.extend(line)
        del tail[:-STDERR_TAIL_BYTES]
    stream.close()
