"""Tests for which of a video's memories a semantic search counts as hits."""

from backend.services.memory_search import (
    DEFAULT_SETTINGS,
    MemorySearchSettings,
    search_memories,
    standout_memories,
)
from backend.services.visual_search import z_scores
from backend.storage.postgres import ScoredMemory
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
MODEL = "intfloat/multilingual-e5-small"
QUERY_VECTOR = [0.1] * 384


def _memory(index: int, similarity: float) -> ScoredMemory:
    return ScoredMemory(
        memory_id=f"memory-{index}",
        chapter_id=None,
        text=f"speech {index}",
        summary=f"summary {index}",
        chapter_title=None,
        start_seconds=index * 10.0,
        end_seconds=index * 10.0 + 8.0,
        similarity=similarity,
    )


def _ids(found) -> list[str]:
    return [memory.memory_id for memory in found.memories]


def test_the_starting_settings_are_the_ones_agreed() -> None:
    assert DEFAULT_SETTINGS == MemorySearchSettings(z_threshold=1.5, max_moments=8, weak_moments=3)


def test_a_hit_is_a_memory_at_or_above_the_z_threshold_and_no_other() -> None:
    # One memory far above the rest, one only a little above them, and the rest level.
    scored = [_memory(0, 0.95), _memory(1, 0.84)] + [_memory(index, 0.80) for index in range(2, 12)]
    z = z_scores([memory.similarity for memory in scored])
    assert z[0] >= 1.5 > z[1]

    found = standout_memories(scored)

    assert _ids(found) == ["memory-0"]
    assert found.nothing_stood_out is False


def test_the_threshold_comes_from_the_settings() -> None:
    scored = [_memory(0, 0.95), _memory(1, 0.84)] + [_memory(index, 0.80) for index in range(2, 12)]

    found = standout_memories(scored, MemorySearchSettings(z_threshold=0.5))

    assert _ids(found) == ["memory-0", "memory-1"]


def test_hits_are_capped_at_eight_closest_first() -> None:
    # Ten memories stand out (z about 2) above forty that do not.
    standing_out = [_memory(index, 0.90 + index * 0.001) for index in range(10)]
    background = [_memory(index, 0.50) for index in range(10, 50)]

    found = standout_memories(background + standing_out)

    assert _ids(found) == [f"memory-{index}" for index in range(9, 1, -1)]
    assert found.nothing_stood_out is False


def test_when_nothing_stands_out_the_three_closest_come_back_as_weak() -> None:
    # Evenly spread: the closest of five is only 1.41 standard deviations up.
    scored = [_memory(index, 0.80 + index * 0.01) for index in range(5)]

    found = standout_memories(scored)

    assert _ids(found) == ["memory-4", "memory-3", "memory-2"]
    assert found.nothing_stood_out is True


def test_every_memory_scoring_the_same_means_nothing_stood_out() -> None:
    found = standout_memories([_memory(index, 0.82) for index in range(10)])

    assert len(found.memories) == 3
    assert found.nothing_stood_out is True


def test_a_video_of_one_memory_follows_the_same_rule() -> None:
    """There is no minimum count: a lone memory has nothing to stand out from, so it comes
    back as the closest one rather than as a hit.
    """
    found = standout_memories([_memory(0, 0.9)])

    assert _ids(found) == ["memory-0"]
    assert found.nothing_stood_out is True


def test_a_video_with_nothing_embedded_finds_nothing_and_nothing_is_weak() -> None:
    found = standout_memories([])

    assert found.memories == []
    assert found.nothing_stood_out is False


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
