"""Tests for how a hybrid search ranks a video's memories: cosine and BM25, fused with RRF."""

from backend.services.memory_search import (
    DEFAULT_SETTINGS,
    MemorySearchSettings,
    fuse_semantic_and_lexical,
    lexical_ranking,
    search_memories,
    semantic_ranking,
)
from backend.storage.postgres import ScoredMemory
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
MODEL = "intfloat/multilingual-e5-small"
QUERY_VECTOR = [0.1] * 384


def _memory(index: int, similarity: float, text: str | None = None) -> ScoredMemory:
    return ScoredMemory(
        memory_id=f"memory-{index}",
        chapter_id=None,
        text=text if text is not None else f"speech {index}",
        summary=f"summary {index}",
        chapter_title=None,
        start_seconds=index * 10.0,
        end_seconds=index * 10.0 + 8.0,
        similarity=similarity,
    )


def _ids(memories) -> list[str]:
    return [memory.memory_id for memory in memories]


def test_the_starting_settings_are_the_ones_agreed() -> None:
    assert DEFAULT_SETTINGS == MemorySearchSettings(max_moments=6, rrf_k=60, bm25_k1=1.2, bm25_b=0.75)


def test_semantic_ranking_is_by_cosine_highest_first() -> None:
    scored = [_memory(0, 0.80), _memory(1, 0.90), _memory(2, 0.85)]

    assert semantic_ranking(scored) == ["memory-1", "memory-2", "memory-0"]


def test_lexical_ranking_leaves_out_memories_sharing_no_word_with_the_query() -> None:
    scored = [
        _memory(0, 0.9, "we talk about the weather"),
        _memory(1, 0.8, "the aligner needs sixteen kilohertz audio"),
        _memory(2, 0.7, "nothing in common here"),
    ]

    assert lexical_ranking(scored, "aligner kilohertz") == ["memory-1"]


def test_lexical_ranking_matches_a_hebrew_word_behind_a_prefix_letter() -> None:
    scored = [
        _memory(0, 0.9, "היום נדבר על מזג האוויר"),
        _memory(1, 0.8, "כתבנו את זה בפייתון"),
    ]

    assert lexical_ranking(scored, "פייתון") == ["memory-1"]


def test_an_exact_term_e5_ranks_last_is_lifted_into_the_results() -> None:
    background = [_memory(index, 0.90 - index * 0.01, f"general talk {index}") for index in range(10)]
    exact = _memory(99, 0.50, "we deploy it with kubernetes on azure")

    found = fuse_semantic_and_lexical(background + [exact], "kubernetes")

    assert "memory-99" in _ids(found)
    assert found[0].memory_id == "memory-99"


def test_with_no_word_in_common_the_order_is_the_cosine_order() -> None:
    scored = [_memory(index, 0.5 + index * 0.01) for index in range(5)]

    found = fuse_semantic_and_lexical(scored, "zzz unmatched")

    assert _ids(found) == ["memory-4", "memory-3", "memory-2", "memory-1", "memory-0"]


def test_there_is_no_gate_and_at_most_six_come_back() -> None:
    scored = [_memory(index, 0.82) for index in range(10)]

    found = fuse_semantic_and_lexical(scored, "anything")

    assert len(found) == 6


def test_a_video_with_fewer_memories_than_the_cap_returns_them_all() -> None:
    found = fuse_semantic_and_lexical([_memory(0, 0.9), _memory(1, 0.8)], "anything")

    assert _ids(found) == ["memory-0", "memory-1"]


def test_a_video_with_nothing_to_search_returns_nothing() -> None:
    assert fuse_semantic_and_lexical([], "anything") == []


def test_the_search_scores_every_memory_of_the_video_with_the_current_model() -> None:
    rows = [
        {
            "memory_id": "memory-0",
            "chapter_id": None,
            "text": "speech",
            "summary": "summary",
            "chapter_title": None,
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "similarity": 0.9,
        }
    ]
    pool = FakePool(rows=rows)

    found = search_memories(VIDEO_ID, "a query", pool=pool, query_encoder=lambda query: QUERY_VECTOR)

    assert pool.recorded[0].parameters == (QUERY_VECTOR, VIDEO_ID, MODEL)
    assert _ids(found) == ["memory-0"]
