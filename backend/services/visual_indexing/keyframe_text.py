"""Reads the on-screen text of a video's keyframes from its local file, a few frames at a time.

This runs after the visual index is stored, so a video can be searched by what it shows while
its text is still being read: OCR is by far the slowest part of indexing, since every frame
with text on it is a VLM decode. Each keyframe is decoded again at full resolution
(`sampling/keyframes.py`), handed to the OCR engine, and turned into the text it stores
(`ocr/text.py`).

The readings come back batch by batch rather than all at the end, so the caller can store each
batch as it is read: an hour of slides is minutes of OCR, and a crash near the end should not
throw away what was read before it. Like the rest of this package, nothing here touches the
database.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..ocr import OcrEngine, OnScreenText, on_screen_text
from .sampling import SamplingStopped, decode_frame_at

# Keyframes handed to the engine at once: as many as Surya's worker reads in parallel, twice.
KEYFRAMES_PER_BATCH = 4

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyframeReading:
    """What one keyframe shows as text; `text` is None when the engine found none worth keeping."""

    time_seconds: float
    text: OnScreenText | None


def read_keyframe_text(
    video_path: Path,
    keyframe_times: Iterable[float],
    engine: OcrEngine,
    *,
    batch_size: int = KEYFRAMES_PER_BATCH,
    stop_event: threading.Event | None = None,
) -> Iterator[list[KeyframeReading]]:
    """Yield the readings of every keyframe, one batch at a time, in time order.

    A time past the video's last frame is left out rather than reported as showing no text,
    since nothing was read there. Raises `SamplingStopped` when `stop_event` is set between
    two batches, and lets the engine's `OcrError` and the decoder's `FrameSamplingError`
    through.
    """
    started = time.perf_counter()
    times = sorted(set(keyframe_times))
    with_text = 0
    for start in range(0, len(times), batch_size):
        if stop_event is not None and stop_event.is_set():
            raise SamplingStopped("Reading on-screen text was stopped")
        decoded = [
            (time_seconds, decode_frame_at(video_path, time_seconds))
            for time_seconds in times[start : start + batch_size]
        ]
        present = [(time_seconds, image) for time_seconds, image in decoded if image is not None]
        if not present:
            continue
        readings = engine.read([image for _, image in present])
        batch = [
            KeyframeReading(time_seconds=time_seconds, text=on_screen_text(reading))
            for (time_seconds, _), reading in zip(present, readings)
        ]
        with_text += sum(1 for reading in batch if reading.text is not None)
        yield batch
    logger.info(
        "Read the on-screen text of %d keyframes of %s with %s: %d show text, in %.1f s",
        len(times),
        video_path.name,
        engine.name,
        with_text,
        time.perf_counter() - started,
    )
