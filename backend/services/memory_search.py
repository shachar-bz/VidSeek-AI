"""`search_memories`: the moments of one video whose speech is closest to a query, by meaning and by words.

Two rankings of the same memories are fused. One is by meaning: every memory of the video is
scored against the query with multilingual-e5-small's cosine similarity (pgvector). The other is
by the words actually said: Okapi BM25 over each memory's spoken text, tokenized for Hebrew and
English (`services/lexical_search`). e5 is good at paraphrase and weak at exact tokens -- a name,
an acronym, a number, an English term inside Hebrew speech -- which is what BM25 catches.

The two are fused with reciprocal rank fusion (`services/rank_fusion.py`) rather than by mixing
scores: a cosine and a BM25 score are on unrelated scales, and RRF uses only each memory's rank in
each list. Only memories that share a word with the query enter the BM25 ranking, so a query with
no word in common with the video falls back to the cosine order.

There is no relevance gate: the closest few always come back, and whoever reads them judges what
they say. A z-score cutoff no longer applies, since fused scores are derived from ranks, not from a
distribution of similarities.

BM25's document frequencies are taken over the video's own memories, which are already loaded for
the cosine ranking. A word the whole video keeps repeating therefore weighs little, and nothing
needs to be stored or kept up to date for it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from backend.services.embeddings.multilingual_text_embedding import MODEL_NAME, embed_query
from backend.services.lexical_search import DEFAULT_B, DEFAULT_K1, bm25_scores, tokenize
from backend.services.rank_fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from backend.storage.postgres import PostgresMemoryEmbeddings, ScoredMemory

QueryEncoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class MemorySearchSettings:
    """The rules the memories are ranked with. Textbook defaults; no eval set has tuned them."""

    # How many moments a search returns. A property of how much speech the agent can usefully
    # read at once, which the model asking the question is not in a position to judge.
    max_moments: int = 6
    # RRF's rank offset: how much rank 1 outweighs rank 10 in either list.
    rrf_k: int = DEFAULT_RRF_K
    # BM25's term-frequency saturation and document-length normalization.
    bm25_k1: float = DEFAULT_K1
    bm25_b: float = DEFAULT_B


DEFAULT_SETTINGS = MemorySearchSettings()


def search_memories(
    video_id: str,
    query: str,
    *,
    settings: MemorySearchSettings = DEFAULT_SETTINGS,
    pool=None,
    query_encoder: QueryEncoder | None = None,
) -> list[ScoredMemory]:
    """The memories of this video closest to `query`, best first, at most `settings.max_moments`.

    Only vectors written by the current text model are scored. The encoder defaults to
    multilingual-e5-small's query embedding; a test replaces it. Empty when the video has no
    memories to search.
    """
    encode = query_encoder if query_encoder is not None else embed_query
    scored = PostgresMemoryEmbeddings(pool).memory_similarities(video_id, encode(query), model=MODEL_NAME)
    return fuse_semantic_and_lexical(scored, query, settings)


def fuse_semantic_and_lexical(
    scored: Sequence[ScoredMemory], query: str, settings: MemorySearchSettings = DEFAULT_SETTINGS
) -> list[ScoredMemory]:
    """One video's memories ranked by cosine and by BM25 on their text, fused with RRF, capped.

    `scored` must be every memory of the video, since BM25's document frequencies are taken over
    all of them. The cosine ranking is passed to RRF first, so a tie between the two goes to the
    memory e5 put higher.
    """
    if not scored:
        return []
    by_id = {memory.memory_id: memory for memory in scored}
    fused = reciprocal_rank_fusion(
        [semantic_ranking(scored), lexical_ranking(scored, query, settings)], k=settings.rrf_k
    )
    return [by_id[memory_id] for memory_id, _ in fused[: settings.max_moments]]


def semantic_ranking(scored: Sequence[ScoredMemory]) -> list[str]:
    """Memory ids by cosine similarity, highest first; equal ones in the order they come in."""
    return [memory.memory_id for memory in sorted(scored, key=lambda memory: -memory.similarity)]


def lexical_ranking(
    scored: Sequence[ScoredMemory], query: str, settings: MemorySearchSettings = DEFAULT_SETTINGS
) -> list[str]:
    """Memory ids by BM25 of the query over their spoken text, highest first; only those matching.

    A memory sharing no word with the query scores 0 and is left out rather than ranked last, so
    it gets no lexical contribution in the fusion instead of a small, meaningless one.
    """
    scores = bm25_scores(
        tokenize(query),
        [tokenize(memory.text) for memory in scored],
        k1=settings.bm25_k1,
        b=settings.bm25_b,
    )
    matching = [(memory.memory_id, score) for memory, score in zip(scored, scores) if score > 0]
    return [memory_id for memory_id, _ in sorted(matching, key=lambda pair: -pair[1])]
