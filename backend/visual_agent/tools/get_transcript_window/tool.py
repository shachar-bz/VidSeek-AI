"""A Pydantic AI tool that reads what was said in a window of the video.

Context for what is shown, never proof of it: the speaker may describe a slide that is not on
screen yet. The window is capped, so one call cannot pour a whole chapter into the
investigation.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.storage.postgres import PostgresTranscriptSegments

from ..budget_spent import BudgetSpent
from ..deps import VisualDeps
from .result import TranscriptPiece, TranscriptWindow

MAX_WINDOW_SECONDS = 180.0

# The most transcript one call returns; pieces past it are left out, and the note says so.
MAX_CHARACTERS = 6000


def get_transcript_window(
    ctx: RunContext[VisualDeps], start_seconds: float, end_seconds: float
) -> TranscriptWindow | BudgetSpent:
    """Read what was said between two times. Costs no image.

    Use it for context around a moment: what the speaker was talking about while something
    was on screen. What is said is not proof of what is shown.

    Args:
        start_seconds: The start of the window, in seconds from the beginning of the video.
        end_seconds: The end of the window, in seconds; at most three minutes after the start.

    Returns:
        Every transcript piece overlapping the window, in order.
    """
    deps = ctx.deps
    if not deps.budget.start_tool_call():
        return BudgetSpent()
    start = max(float(start_seconds), 0.0)
    end = max(float(end_seconds), start)
    notes = []
    if end - start > MAX_WINDOW_SECONDS:
        end = start + MAX_WINDOW_SECONDS
        notes.append(f"The window was cut to its first {MAX_WINDOW_SECONDS:g} seconds.")
    segments = PostgresTranscriptSegments(deps.pool).overlapping(deps.video_id, start, end)
    pieces = []
    characters = 0
    for segment in segments:
        characters += len(segment.text)
        if pieces and characters > MAX_CHARACTERS:
            notes.append(f"Only the first {len(pieces)} pieces are given; the rest were too long.")
            break
        deps.record_span(segment.start_seconds, segment.end_seconds)
        pieces.append(
            TranscriptPiece(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=segment.text,
            )
        )
    return TranscriptWindow(
        start_seconds=start,
        end_seconds=end,
        chapter=deps.chapter_at(start),
        pieces=pieces,
        note=" ".join(notes) or None,
        budget=deps.budget.remaining(),
    )
