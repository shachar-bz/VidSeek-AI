"""`search_visual_text`: the moments of one video whose on-screen text contains given words.

Each word is looked for in every keyframe's OCR text as a sequence of characters, not as a whole
word (VISUAL_UNDERSTANDING_PLAN.md §5.2). Both sides are case folded and have every whitespace
character removed first, so "kafka partitions" also finds "Kafka" and "Partitions" on two lines,
or an OCR line split as "Kaf ka partitions". So "כוס" finds "הכוס", and "cup" finds "cupboard":
that is accepted, because the sub-agent reads the text and can tell.

A keyframe matches when at least one word is found in it. There is no score and no threshold.
Moments are ordered by how many different words were found in them, then by time. A misreading
("Partitons") is not found; the text-by-meaning list of `search_visual_moments` is there for it.

The matching is done here rather than in SQL: a video has a few hundred keyframes at most, and
reading them all costs less than keeping an index for it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .moments import (
    INDEX_READY,
    TEXT_CHARACTERS,
    FoundMoment,
    TimeWindow,
    VisualSearchResult,
    fill_moments,
    keyframe_text_moments,
    open_index,
)

# How many words one search may look for, and how many moments it returns at most.
MAX_WORDS = 5
MAX_MOMENTS = 5


def search_visual_text(
    video_id: str,
    words: Sequence[str],
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    pool=None,
) -> VisualSearchResult:
    """The moments of this video showing any of `words` on screen, within the window if one is given.

    Raises `ValueError` for no words, more than `MAX_WORDS`, or a word that is empty once its
    whitespace is removed.
    """
    wanted = _wanted_words(words)
    window = TimeWindow(start_seconds, end_seconds)
    opened = open_index(video_id, pool=pool)
    if isinstance(opened, VisualSearchResult):
        return opened

    found_at: dict[float, set[str]] = {}
    for time_seconds, text in opened.keyframe_texts.items():
        screen = normalized(text)
        found = {spelling for spelling, form in wanted if form in screen}
        if found:
            found_at[time_seconds] = found

    ranked = []
    for moment in keyframe_text_moments(found_at, opened.video_map, window):
        found_here = set().union(*(found_at[time] for time in moment.keyframe_times))
        # The keyframe that shows the most of the words, the earliest of those.
        shown = max(moment.keyframe_times, key=lambda time: (len(found_at[time]), -time))
        ranked.append(
            FoundMoment(
                segment=moment.segment,
                start_seconds=moment.start_seconds,
                end_seconds=moment.end_seconds,
                found_by=(TEXT_CHARACTERS,),
                keyframe_time_seconds=shown,
                matched_words=tuple(spelling for spelling, _ in wanted if spelling in found_here),
            )
        )
    ranked.sort(key=lambda moment: (-len(moment.matched_words), moment.start_seconds))
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=opened.visual_status,
        moments=fill_moments(ranked[:MAX_MOMENTS], opened, pool=pool),
        unread_keyframe_count=opened.unread_keyframe_count,
    )


def normalized(text: str) -> str:
    """The text as both sides are compared: case folded, with every whitespace character removed."""
    return "".join(text.split()).casefold()


def _wanted_words(words: Sequence[str]) -> list[tuple[str, str]]:
    """Each word as the caller wrote it and as it is compared, once per compared form, in order."""
    if isinstance(words, str) or not isinstance(words, Sequence):
        raise ValueError("words must be a list of strings, not a single string")
    if not 1 <= len(words) <= MAX_WORDS:
        raise ValueError(f"give 1 to {MAX_WORDS} words to look for, not {len(words)}")
    wanted: list[tuple[str, str]] = []
    for word in words:
        if not isinstance(word, str):
            raise ValueError(f"{word!r} is not a string")
        form = normalized(word)
        if not form:
            raise ValueError("a word to look for is empty once its whitespace is removed")
        if all(form != seen for _, seen in wanted):
            wanted.append((word, form))
    return wanted
