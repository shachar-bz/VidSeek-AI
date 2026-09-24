"""Tests for the visual index store and the memory similarity read: the SQL they send and what they read back."""

import pytest

from backend.storage.postgres import (
    KeyframeText,
    NewFrameEmbedding,
    NewVisualSegment,
    PostgresMemoryEmbeddings,
    PostgresVisualIndex,
)
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def test_state_reads_the_status_columns_off_the_video_row() -> None:
    pool = FakePool(
        rows=[{"visual_status": "ready", "visual_error": None, "visual_index_version": "v1"}]
    )

    state = PostgresVisualIndex(pool=pool).state(VIDEO_ID)

    assert (state.status, state.error, state.index_version) == ("ready", None, "v1")
    assert pool.recorded[0].parameters == (VIDEO_ID,)


def test_state_of_a_video_that_does_not_exist_is_none() -> None:
    assert PostgresVisualIndex(pool=FakePool()).state(VIDEO_ID) is None


def test_mark_writes_status_and_error_but_never_ready() -> None:
    pool = FakePool()
    store = PostgresVisualIndex(pool=pool)

    store.mark(VIDEO_ID, "failed", error="visual_indexing_failed")

    assert pool.recorded[0].parameters == ("failed", "visual_indexing_failed", VIDEO_ID)
    # `ready` comes only with the rows that make an index ready.
    with pytest.raises(ValueError):
        store.mark(VIDEO_ID, "ready")
    with pytest.raises(ValueError):
        store.mark(VIDEO_ID, "done")


def test_replace_swaps_the_whole_index_and_marks_it_ready_in_one_transaction() -> None:
    pool = FakePool()

    PostgresVisualIndex(pool=pool).replace(
        VIDEO_ID,
        frames=[NewFrameEmbedding(0.0, [1.0, 0.0]), NewFrameEmbedding(2.0, [0.0, 1.0])],
        segments=[
            NewVisualSegment(1, 2.0, 4.0, "scene_change", (2.0,)),
            NewVisualSegment(0, 0.0, 2.0, "video_start", (0.0,)),
        ],
        index_version="siglip2-base-patch16-256@0.5fps",
    )

    assert pool.transactions == 1
    statements = pool.statements
    assert statements[0].startswith("delete from public.video_frame_embeddings")
    assert statements[1].startswith("delete from public.video_visual_segments")
    frames, segments, keyframes, ready = pool.recorded[2:]
    assert frames.many and frames.parameters == [
        (VIDEO_ID, 0.0, [1.0, 0.0]),
        (VIDEO_ID, 2.0, [0.0, 1.0]),
    ]
    # Written in position order whatever order they were handed over in.
    assert [row[1] for row in segments.parameters] == [0, 1]
    assert keyframes.parameters == [(VIDEO_ID, 0.0, VIDEO_ID, 0), (VIDEO_ID, 2.0, VIDEO_ID, 1)]
    assert "visual_status = 'ready'" in ready.statement
    assert ready.parameters == ("siglip2-base-patch16-256@0.5fps", VIDEO_ID)


def test_every_frame_of_the_video_is_scored_in_time_order() -> None:
    pool = FakePool(rows=[{"time_seconds": 0.0, "similarity": 0.1}, {"time_seconds": 2.0, "similarity": 0.2}])

    scored = PostgresVisualIndex(pool=pool).frame_similarities(VIDEO_ID, [0.5, 0.5])

    assert [(s.time_seconds, s.similarity) for s in scored] == [(0.0, 0.1), (2.0, 0.2)]
    assert "limit" not in pool.statements[0]
    assert "order by time_seconds" in pool.statements[0]
    assert pool.recorded[0].parameters == ([0.5, 0.5], VIDEO_ID)


def test_segments_are_read_with_their_keyframes_for_an_open_or_closed_window() -> None:
    row = {
        "segment_id": "seg-1",
        "segment_index": 0,
        "start_seconds": 0.0,
        "end_seconds": 12.0,
        "boundary_kind": "video_start",
        "keyframe_times": [0.0, 60.0],
    }
    pool = FakePool(rows=[row])
    store = PostgresVisualIndex(pool=pool)

    whole = store.segments(VIDEO_ID)
    window = store.segments(VIDEO_ID, start_seconds=5.0, end_seconds=9.0)

    assert whole[0].keyframe_times == (0.0, 60.0)
    assert pool.recorded[0].parameters == (VIDEO_ID, None, None, None, None)
    assert pool.recorded[1].parameters == (VIDEO_ID, 5.0, 5.0, 9.0, 9.0)
    assert window[0].segment_id == "seg-1"


def test_memory_similarities_carry_the_score_the_search_floors_on() -> None:
    pool = FakePool(
        rows=[{"memory_id": "m1", "start_seconds": 30.0, "end_seconds": 55.0, "similarity": 0.42}]
    )

    matches = PostgresMemoryEmbeddings(pool=pool).memory_similarities(VIDEO_ID, [0.1], 5)

    assert [(m.memory_id, m.start_seconds, m.end_seconds, m.similarity) for m in matches] == [
        ("m1", 30.0, 55.0, 0.42)
    ]
    assert pool.recorded[0].parameters == ([0.1], VIDEO_ID, [0.1], 5)


def test_keyframe_text_is_written_onto_the_keyframe_rows_with_the_engine_that_read_it() -> None:
    pool = FakePool()

    written = PostgresVisualIndex(pool=pool).set_keyframe_text(
        VIDEO_ID,
        [
            KeyframeText(0.0, "System design", "en", 0.93, [0.1, 0.2]),
            KeyframeText(60.0, None),
        ],
        engine="surya-ocr-2",
    )

    assert written == 2
    update = pool.recorded[0]
    assert update.many and update.statement.lstrip().startswith("update public.video_keyframes")
    assert update.parameters == [
        ("System design", "en", 0.93, [0.1, 0.2], "surya-ocr-2", VIDEO_ID, 0.0),
        # Read and blank: the engine is recorded so the keyframe is not read again for nothing.
        (None, None, None, None, "surya-ocr-2", VIDEO_ID, 60.0),
    ]


def test_writing_no_keyframe_text_touches_nothing() -> None:
    pool = FakePool()

    assert PostgresVisualIndex(pool=pool).set_keyframe_text(VIDEO_ID, [], engine="surya-ocr-2") == 0
    assert pool.recorded == []


def test_keyframe_text_is_counted_and_searched_by_words_and_by_meaning() -> None:
    match = {"time_seconds": 40.0, "ocr_text": "Load balancer", "similarity": 0.75}
    pool = FakePool(responses=[[{"text_count": 3}], [match], [match]])
    store = PostgresVisualIndex(pool=pool)

    assert store.keyframe_text_count(VIDEO_ID) == 3
    by_words = store.keyframe_text_word_matches(VIDEO_ID, "load balancer", 10)
    by_meaning = store.keyframe_text_similarities(VIDEO_ID, [0.4], 10)

    assert (by_words[0].time_seconds, by_words[0].text, by_words[0].similarity) == (40.0, "Load balancer", 0.75)
    assert "word_similarity" in pool.statements[1]
    assert pool.recorded[1].parameters == ("load balancer", VIDEO_ID, 10)
    assert by_meaning[0].text == "Load balancer"
    assert pool.recorded[2].parameters == ([0.4], VIDEO_ID, [0.4], 10)


def test_a_video_with_no_keyframe_text_counts_zero() -> None:
    assert PostgresVisualIndex(pool=FakePool()).keyframe_text_count(VIDEO_ID) == 0
