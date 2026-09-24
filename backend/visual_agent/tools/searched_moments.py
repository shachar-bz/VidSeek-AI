"""What both search tools hand the sub-agent: the moments a search found, or why it found none.

`search_visual_moments` and `search_visual_text` return the same shape, built here from the
search service's result (`services/visual_search/`). Every moment carries plain `start_seconds`
and `end_seconds`. A moment found by its on-screen text is recorded as a span the findings check
accepts: the text was read there, so the sub-agent may cite it. A moment found only by its
picture is not: resembling the query is not showing it, so it is marked `needs_look` and becomes
citable only once `view_sequence` or `view_frames_closeup` has looked at it.

A search that could not run -- the index is not built yet, or was built with other models --
returns no moments and a note telling the agent to look at the frames instead. While OCR is
still reading keyframes, the note says so, so an empty text search is not read as "not on
screen".
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.services.video_frames import format_timestamp
from backend.services.visual_search import (
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    TEXT_CHARACTERS,
    TEXT_MEANING,
    VisualSearchResult,
)

from .deps import VisualDeps


class SearchedMoment(BaseModel):
    """One stretch of the video a search found, where it is, and what surrounds it."""

    start_seconds: float = Field(description="Where the moment starts, in seconds from the beginning of the video.")
    end_seconds: float = Field(description="Where the moment ends, in seconds from the beginning of the video.")
    timestamps: str = Field(description="The same stretch written as MM:SS-MM:SS.")
    chapter: str | None = Field(default=None, description="The title of the chapter the moment starts in, if any.")
    segment_index: int = Field(description="The visual segment the moment lies in: one uninterrupted shot or screen.")
    segment_boundary: str = Field(
        description=(
            "How the segment began: `video_start`, `scene_change` (a new shot or scene) or "
            "`text_change` (new text on the same screen, such as the next slide)."
        )
    )
    found_by: list[str] = Field(
        description=(
            "What matched: `image` (the picture resembles the query), `text_meaning` (the "
            "on-screen text means what the query does), `text_characters` (the words asked for "
            "are written on screen)."
        )
    )
    on_screen_text: str | None = Field(
        default=None, description="The text read on screen at this moment, possibly cut; None when there is none."
    )
    transcript: str | None = Field(
        default=None, description="What was said while it was on screen, possibly cut; None when nothing was."
    )
    peak_z_score: float | None = Field(
        default=None,
        description="How far the best frame's picture stood out from the rest of the video; higher is a stronger match.",
    )
    matched_words: list[str] = Field(
        default_factory=list, description="The words asked for that are written on screen here."
    )
    needs_look: bool = Field(
        default=False,
        description=(
            "True when only the picture matched: a lead, not proof. Look at it with view_sequence "
            "before saying what it shows; until then it cannot be cited as a finding."
        ),
    )


class SearchedMoments(BaseModel):
    """What one search found, best first, and anything the agent should know about it."""

    moments: list[SearchedMoment] = Field(default_factory=list, description="The moments found, best first.")
    note: str | None = Field(default=None, description="Why nothing was found or searched, or what may be missing.")
    budget: str = Field(description="What is left of the investigation's budget.")


def searched_moments(
    deps: VisualDeps, result: VisualSearchResult, notes: list[str]
) -> SearchedMoments:
    """The service's result as the agent reads it, each moment recorded as a span it may cite."""
    notes = list(notes)
    if result.index_status in (INDEX_NOT_READY, INDEX_OUTDATED):
        notes.append(unsearchable_note(deps, result))
        return SearchedMoments(note=" ".join(notes), budget=deps.budget.remaining())

    moments = []
    for moment in result.moments:
        needs_look = not (TEXT_MEANING in moment.found_by or TEXT_CHARACTERS in moment.found_by)
        if not needs_look:
            deps.record_span(moment.start_seconds, moment.end_seconds)
        moments.append(
            SearchedMoment(
                start_seconds=moment.start_seconds,
                end_seconds=moment.end_seconds,
                timestamps=f"{format_timestamp(moment.start_seconds)}-{format_timestamp(moment.end_seconds)}",
                chapter=moment.chapter.title if moment.chapter is not None else None,
                segment_index=moment.segment.segment_index,
                segment_boundary=moment.segment.boundary_kind,
                found_by=list(moment.found_by),
                on_screen_text=moment.on_screen_text,
                transcript=moment.transcript,
                peak_z_score=round(moment.peak_z_score, 2) if moment.peak_z_score is not None else None,
                matched_words=list(moment.matched_words),
                needs_look=needs_look,
            )
        )
    if not moments:
        notes.append("Nothing matched.")
    if result.ocr_pending:
        notes.append(
            f"OCR has not read the text of {result.unread_keyframe_count} keyframes yet, so text "
            "written on screen there cannot be found by this search."
        )
    return SearchedMoments(moments=moments, note=" ".join(notes) or None, budget=deps.budget.remaining())


def unsearchable_note(deps: VisualDeps, result: VisualSearchResult) -> str:
    """Why the index could not be searched, and what to do instead."""
    if result.index_status == INDEX_OUTDATED:
        reason = "The video's visual index was built with other models than the current ones, so it cannot be searched."
    else:
        status = f" (status: {result.visual_status})" if result.visual_status else ""
        reason = f"The video's visual index is not ready{status}, so it cannot be searched."
    if deps.current_time_seconds is None:
        instead = "Look at the frames the question points to with view_sequence or read_frame_text instead."
    else:
        instead = (
            "Look at the viewer's current moment, "
            f"{format_timestamp(deps.current_time_seconds)} ({deps.current_time_seconds:.1f} s), "
            "with view_sequence or read_frame_text instead."
        )
    return f"{reason} {instead}"


def search_window(
    start_seconds: float | None, end_seconds: float | None
) -> tuple[float | None, float | None] | str:
    """The window to search, a start before the video moved to its beginning; a note when it ends before it starts."""
    start = max(float(start_seconds), 0.0) if start_seconds is not None else None
    end = float(end_seconds) if end_seconds is not None else None
    if end is not None and end < (start or 0.0):
        return (
            "Nothing was searched, and no tool call was spent: end_seconds is before start_seconds. "
            "Give a window that ends after it starts, or leave both out to search the whole video."
        )
    return start, end
