"""`search_memories`: the moments of one video whose speech is closest in meaning to a query.

Every memory of the video is scored against the query with multilingual-e5-small, and a memory
is a hit when it stands out from the rest of *its own video's* scores: its z-score against all of
them is at least the threshold. There is no fixed minimum similarity, for the reason
`visual_search/scoring.py` gives: e5's cosines are high and bunched together, and the same
number means something different in every video. The hits come back closest first, capped.

When no memory stands out, the search does not answer with nothing: it returns the few closest
memories, marked as nothing having stood out, so the caller can say so. Unlike a weak frame, a
weak memory is still real retrieved speech -- its text is what was said -- so it is only
probably off the question, not unseen.

The same rule holds for every video whatever its number of memories. Most have between nine and
forty-odd, enough for a z-score to mean something; a video with one memory, or with every score
equal, has no spread to stand out from, and falls through to the closest memories.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from backend.services.embeddings.multilingual_text_embedding import MODEL_NAME, embed_query
from backend.services.visual_search import z_scores
from backend.storage.postgres import PostgresMemoryEmbeddings, ScoredMemory

QueryEncoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class MemorySearchSettings:
    """The rules the memories are read with. Starting values; the eval set tunes them."""

    # How far above its video's mean, in standard deviations, a memory must score to be a hit.
    z_threshold: float = 1.5
    # How many hits a search returns at most. A property of how much speech the agent can
    # usefully read at once, which the model asking the question is not in a position to judge.
    max_moments: int = 8
    # How many of the closest memories come back, marked weak, when none stood out.
    weak_moments: int = 3


DEFAULT_SETTINGS = MemorySearchSettings()


@dataclass(frozen=True)
class FoundMemories:
    """What one search found, closest first, and whether any of it actually stood out.

    `nothing_stood_out` is set when no memory was a hit and `memories` holds only the closest
    ones instead. A video with nothing to search has no memories and nothing standing out.
    """

    memories: list[ScoredMemory]
    nothing_stood_out: bool


def search_memories(
    video_id: str,
    query: str,
    *,
    settings: MemorySearchSettings = DEFAULT_SETTINGS,
    pool=None,
    query_encoder: QueryEncoder | None = None,
) -> FoundMemories:
    """The memories of this video whose speech stands out as closest to `query`.

    Only vectors written by the current text model are scored. The encoder defaults to
    multilingual-e5-small's query embedding; a test replaces it.
    """
    encode = query_encoder if query_encoder is not None else embed_query
    scored = PostgresMemoryEmbeddings(pool).memory_similarities(video_id, encode(query), model=MODEL_NAME)
    return standout_memories(scored, settings)


def standout_memories(
    scored: Sequence[ScoredMemory], settings: MemorySearchSettings = DEFAULT_SETTINGS
) -> FoundMemories:
    """Which of one video's scored memories are hits, closest first, or the closest few if none is.

    `scored` must be every memory of the video, since each one's z-score is taken against all
    of them.
    """
    if not scored:
        return FoundMemories(memories=[], nothing_stood_out=False)
    memory_z_scores = z_scores([memory.similarity for memory in scored])
    hits = [memory for memory, z in zip(scored, memory_z_scores) if z >= settings.z_threshold]
    if hits:
        return FoundMemories(memories=_closest_first(hits)[: settings.max_moments], nothing_stood_out=False)
    return FoundMemories(memories=_closest_first(scored)[: settings.weak_moments], nothing_stood_out=True)


def _closest_first(memories: Sequence[ScoredMemory]) -> list[ScoredMemory]:
    """Highest similarity first; equal ones in the order they come in."""
    return sorted(memories, key=lambda memory: -memory.similarity)
