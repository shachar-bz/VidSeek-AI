"""A Pydantic AI tool that reads the text shown on screen at given times.

Indexing already read the text of every keyframe, and a keyframe's text stands for the stretch
from it to the next keyframe of its segment, or to the segment's end: a new slide or new text
on a board starts a new segment (VISUAL_UNDERSTANDING_PLAN.md §5.3). So a time inside a read
keyframe's stretch is answered from the database, at no cost. Any other time -- before the
index is ready, while OCR is still reading, or in the few seconds between a segment's boundary
and its first keyframe -- is read now: the frame is extracted from the stored video at full
size, losslessly, and handed to the same OCR engine indexing uses. Neither costs an image.

Reading now is slow (seconds per frame on the developer machine, and the first read of a
process starts the OCR worker), and it needs OCR to be set up; without it, those times come
back unread, and the agent is told to look at the frame instead.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence

from PIL import Image, UnidentifiedImageError
from pydantic_ai import RunContext

from backend.services.video_frames import (
    READABLE_LONG_SIDE,
    FrameExtractionError,
    VideoNotStoredError,
    format_timestamp,
)
from backend.services.visual_indexing.ocr import OcrError, on_screen_text
from backend.storage.postgres import PostgresVisualIndex, StoredKeyframe

from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from .result import READ_NOW, STORED, UNREAD, FrameText, FrameTexts

MAX_TIMESTAMPS_PER_CALL = 6

# A slide can hold a lot of text; more than this per frame is cut, and says so.
MAX_TEXT_CHARACTERS = 2000


async def read_frame_text(
    ctx: RunContext[VisualDeps], timestamps: list[float]
) -> FrameTexts | BudgetSpent:
    """Read the text shown on screen at these times: slides, boards, code, captions.

    Costs no image, and reads small print better than any look at the picture. Text already
    read when the video was indexed is returned at once, with the stretch of video it is shown
    for; any other time is read now, which takes a few seconds per frame. Use it for the whole
    text when a search moment's on_screen_text was cut.

    Args:
        timestamps: The times to read, in seconds from the beginning of the video; at most six.

    Returns:
        The text at each time, in the same order; `text` is None where nothing is written,
        and where it could not be read (`source` is `unread`, and the note says why).
    """
    deps = ctx.deps
    times = list(dict.fromkeys(max(float(time_seconds), 0.0) for time_seconds in timestamps))
    if not times:
        return FrameTexts(
            note="Nothing was read, and no tool call was spent: no times were given.",
            budget=deps.budget.remaining(),
        )
    if not deps.budget.start_tool_call():
        return BudgetSpent()
    note = None
    if len(times) > MAX_TIMESTAMPS_PER_CALL:
        note = f"Only the first {MAX_TIMESTAMPS_PER_CALL} times were read."
        times = times[:MAX_TIMESTAMPS_PER_CALL]

    keyframes = await asyncio.to_thread(PostgresVisualIndex(deps.pool).keyframes, deps.video_id)
    texts: dict[float, FrameText] = {}
    to_read = []
    for time_seconds in times:
        covering = covering_keyframe(keyframes, time_seconds)
        if covering is None:
            to_read.append(time_seconds)
            continue
        keyframe, stretch_end = covering
        texts[time_seconds] = _frame_text(
            deps, time_seconds, keyframe.text, STORED, keyframe.time_seconds, stretch_end
        )
    if to_read:
        texts.update(await _read_now(deps, to_read))

    for text in texts.values():
        if text.source != UNREAD:
            deps.record_span(text.start_seconds, text.end_seconds)
    return FrameTexts(
        texts=[texts[time_seconds] for time_seconds in times],
        note=note,
        budget=deps.budget.remaining(),
    )


def covering_keyframe(
    keyframes: Sequence[StoredKeyframe], time_seconds: float
) -> tuple[StoredKeyframe, float] | None:
    """The read keyframe whose text stands for this time, and where its stretch ends.

    A keyframe's stretch runs from it to the next keyframe of its segment, or to the segment's
    end. None when the time is in no stretch, or the keyframe covering it was not read yet.
    """
    for position, keyframe in enumerate(keyframes):
        following = keyframes[position + 1] if position + 1 < len(keyframes) else None
        stretch_end = (
            following.time_seconds
            if following is not None and following.segment_index == keyframe.segment_index
            else keyframe.segment_end_seconds
        )
        if keyframe.time_seconds <= time_seconds < stretch_end:
            return (keyframe, stretch_end) if keyframe.engine is not None else None
    return None


async def _read_now(deps: VisualDeps, times: list[float]) -> dict[float, FrameText]:
    """The text of each frame, read now with the OCR engine; unread, with the reason, when it cannot be."""
    engine = await asyncio.to_thread(deps.ocr_engine)
    if engine is None:
        return _unread(deps, times, "OCR is not set up on this machine; look at the frame with view_frames_closeup to read it.")
    try:
        frames = await asyncio.to_thread(
            deps.frames().frames,
            deps.video_id,
            times,
            long_side=READABLE_LONG_SIDE,
            lossless=True,
        )
    except (FrameExtractionError, VideoNotStoredError) as error:
        return _unread(deps, times, f"The frames could not be extracted: {error}")
    try:
        images = [Image.open(io.BytesIO(frame.image_bytes)).convert("RGB") for frame in frames]
    except (UnidentifiedImageError, OSError) as error:
        return _unread(deps, times, f"The extracted frames could not be decoded: {error}")
    try:
        readings = await asyncio.to_thread(engine.read, images)
    except OcrError as error:
        return _unread(deps, times, f"OCR failed: {error}")
    # An engine owes one reading per image; a time it gave none for comes back unread rather
    # than silently missing from the answer.
    found = _unread(deps, times[len(readings):], "OCR returned no reading for this frame.")
    for time_seconds, reading in zip(times, readings):
        text = on_screen_text(reading)
        found[time_seconds] = _frame_text(
            deps, time_seconds, text.text if text else None, READ_NOW, time_seconds, time_seconds
        )
    return found


def _unread(deps: VisualDeps, times: list[float], reason: str) -> dict[float, FrameText]:
    return {
        time_seconds: _frame_text(
            deps, time_seconds, None, UNREAD, time_seconds, time_seconds, note=reason
        )
        for time_seconds in times
    }


def _frame_text(
    deps: VisualDeps,
    time_seconds: float,
    text: str | None,
    source: str,
    start_seconds: float,
    end_seconds: float,
    *,
    note: str | None = None,
) -> FrameText:
    if text is not None and len(text) > MAX_TEXT_CHARACTERS:
        text = text[:MAX_TEXT_CHARACTERS] + " [cut]"
    return FrameText(
        time_seconds=time_seconds,
        timestamp=format_timestamp(time_seconds),
        text=text,
        source=source,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        chapter=deps.chapter_at(time_seconds),
        note=note,
    )
