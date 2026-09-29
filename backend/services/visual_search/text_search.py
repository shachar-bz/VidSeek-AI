"""`search_screen_text`: the moments of one video by the text written on screen.

Two lists are read, and never combined by score or merged into one another:

* by meaning -- every keyframe's on-screen text scored against the query with
  multilingual-e5-small. A text is a hit when it stands out from the video's other texts; with
  too few texts for that to mean anything, the closest are taken. Ranked by the best similarity.
* by exact words, when words are given -- each word looked for in every keyframe's OCR text as
  a sequence of characters, not as a whole word (VISUAL_UNDERSTANDING_PLAN.md §5.2). Both sides
  are case folded and have every whitespace character removed first, so "kafka partitions" also
  finds "Kafka" and "Partitions" on two lines, or an OCR line split as "Kaf ka partitions". So
  "כוס" finds "הכוס", and "cup" finds "cupboard": that is accepted, because the agent reads the
  text and can tell. There is no score; moments are ordered by how many different words were
  found in them, then by time. A misreading ("Partitons") is not found: the meaning list is
  there for it.

Each list keeps its best five moments. The exact-word moments come first, then the ones found
by meaning; a segment both lists found appears once in each.

`search_visual_text` is the exact-word list alone, for the visual sub-agent's tool until it is
removed.

The matching is done here rather than in SQL: a video has a few hundred keyframes at most, and
reading them all costs less than keeping an index for it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from backend.storage.postgres import PostgresVisualIndex

from .moments import (
    INDEX_READY,
    TEXT_CHARACTERS,
    TEXT_MEANING,
    FoundMoment,
    SearchContext,
    VisualSearchResult,
    fill_moments,
    keyframe_text_moments,
    open_index,
)
from .scoring import standout_positions

QueryEncoder = Callable[[str], list[float]]

# How many words one search may look for, and how many moments each list returns at most.
MAX_WORDS = 5
MAX_MOMENTS = 5

# How far above the video's mean, in standard deviations, a keyframe's text must score by
# meaning to be a hit; and with fewer texts than the minimum, a z-score over them means little,
# and the closest are taken instead. Starting values; the eval set tunes them.
MEANING_Z_THRESHOLD = 1.5
MINIMUM_TEXTS_FOR_Z_SCORE = 20


def search_screen_text(
    video_id: str,
    query: str,
    words: Sequence[str] | None = None,
    *,
    pool=None,
    on_screen_text_query_encoder: QueryEncoder | None = None,
) -> VisualSearchResult:
    """The moments of this video whose on-screen text means what `query` does, or shows any of `words`.

    The encoder defaults to multilingual-e5-small; a test replaces it. e5 is not loaded for a
    video none of whose keyframes show text. Raises `ValueError` for words that cannot be
    searched for, as `search_visual_text` does, before anything is read.
    """
    wanted = _wanted_words(words) if words is not None else []
    opened = open_index(video_id, pool=pool)
    if isinstance(opened, VisualSearchResult):
        return opened

    by_words = _word_moments(opened, wanted)[:MAX_MOMENTS] if wanted else []
    by_meaning = (
        _meaning_moments(opened, query, pool, on_screen_text_query_encoder)[:MAX_MOMENTS]
        if opened.keyframe_texts
        else []
    )
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=opened.visual_status,
        moments=fill_moments(by_words + by_meaning, opened),
        unread_keyframe_count=opened.unread_keyframe_count,
    )


def search_visual_text(video_id: str, words: Sequence[str], *, pool=None) -> VisualSearchResult:
    """The moments of this video showing any of `words` on screen.

    Raises `ValueError` for no words, more than `MAX_WORDS`, or a word that is empty once its
    whitespace is removed.
    """
    wanted = _wanted_words(words)
    opened = open_index(video_id, pool=pool)
    if isinstance(opened, VisualSearchResult):
        return opened
    return VisualSearchResult(
        index_status=INDEX_READY,
        visual_status=opened.visual_status,
        moments=fill_moments(_word_moments(opened, wanted)[:MAX_MOMENTS], opened),
        unread_keyframe_count=opened.unread_keyframe_count,
    )


def normalized(text: str) -> str:
    """The text as both sides are compared: case folded, with every whitespace character removed."""
    return "".join(text.split()).casefold()


def _word_moments(context: SearchContext, wanted: list[tuple[str, str]]) -> list[FoundMoment]:
    """The segments whose keyframes show any of the words, the most different words first."""
    found_at: dict[float, set[str]] = {}
    for time_seconds, text in context.keyframe_texts.items():
        screen = normalized(text)
        found = {spelling for spelling, form in wanted if form in screen}
        if found:
            found_at[time_seconds] = found

    ranked = []
    for moment in keyframe_text_moments(found_at, context.video_map):
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
    return ranked


def _meaning_moments(
    context: SearchContext, query: str, pool, encoder: QueryEncoder | None
) -> list[FoundMoment]:
    """The keyframe texts that mean what the query does, one moment per segment, closest first."""
    if encoder is None:
        from backend.services.embeddings.multilingual_text_embedding import embed_query

        encoder = embed_query
    scored = PostgresVisualIndex(pool=pool).keyframe_text_similarities(
        context.video_id, encoder(query)
    )
    positions = standout_positions(
        [match.similarity for match in scored],
        z_threshold=MEANING_Z_THRESHOLD,
        minimum_for_z_score=MINIMUM_TEXTS_FOR_Z_SCORE,
    )
    similarity_at = {scored[position].time_seconds: scored[position].similarity for position in positions}

    ranked = []
    for moment in keyframe_text_moments(similarity_at, context.video_map):
        best_keyframe = max(moment.keyframe_times, key=lambda time: similarity_at[time])
        ranked.append(
            (
                similarity_at[best_keyframe],
                FoundMoment(
                    segment=moment.segment,
                    start_seconds=moment.start_seconds,
                    end_seconds=moment.end_seconds,
                    found_by=(TEXT_MEANING,),
                    keyframe_time_seconds=best_keyframe,
                ),
            )
        )
    ranked.sort(key=lambda entry: (-entry[0], entry[1].start_seconds))
    return [moment for _, moment in ranked]


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
