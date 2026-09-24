"""Tests for the visual index and frame caption stores: the SQL they send and what they read back."""

import pytest

from backend.storage.postgres import (
    NewFrameCaption,
    NewFrameEmbedding,
    NewVisualSegment,
    PostgresFrameCaptions,
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


def test_captions_are_appended_with_their_vectors_and_model() -> None:
    pool = FakePool()

    written = PostgresFrameCaptions(pool=pool).add(
        VIDEO_ID,
        [
            NewFrameCaption(12.0, "A whiteboard with a diagram", [0.1], "gpt-vision"),
            NewFrameCaption(20.0, "A man lifts a cup", [0.2], "gpt-vision", end_seconds=26.0),
        ],
    )

    assert written == 2
    assert pool.recorded[0].many
    assert pool.recorded[0].parameters[1] == (
        VIDEO_ID, 20.0, 26.0, "A man lifts a cup", [0.2], "gpt-vision"
    )


def test_adding_no_captions_touches_nothing() -> None:
    pool = FakePool()

    assert PostgresFrameCaptions(pool=pool).add(VIDEO_ID, []) == 0
    assert pool.recorded == []


def test_captions_are_read_by_window_and_scored_by_meaning() -> None:
    pool = FakePool(
        responses=[
            [{"caption_count": 2}],
            [
                {
                    "id": "c1",
                    "time_seconds": 12.0,
                    "end_seconds": None,
                    "caption": "A whiteboard",
                    "model": "gpt-vision",
                    "created_at": "2026-09-23T10:00:00+00:00",
                }
            ],
            [{"id": "c1", "time_seconds": 12.0, "end_seconds": None, "caption": "A whiteboard", "similarity": 0.91}],
        ]
    )
    store = PostgresFrameCaptions(pool=pool)

    assert store.count(VIDEO_ID) == 2
    window = store.in_window(VIDEO_ID, start_seconds=10.0, end_seconds=14.0)
    scored = store.similarities(VIDEO_ID, [0.3])

    assert window[0].end_seconds is None and window[0].caption == "A whiteboard"
    assert pool.recorded[1].parameters == (VIDEO_ID, 10.0, 10.0, 14.0, 14.0)
    assert scored[0].similarity == 0.91
    assert pool.recorded[2].parameters == ([0.3], VIDEO_ID, [0.3])


def test_memory_similarities_carry_the_score_the_search_floors_on() -> None:
    pool = FakePool(
        rows=[{"memory_id": "m1", "start_seconds": 30.0, "end_seconds": 55.0, "similarity": 0.42}]
    )

    matches = PostgresMemoryEmbeddings(pool=pool).memory_similarities(VIDEO_ID, [0.1], 5)

    assert [(m.memory_id, m.start_seconds, m.end_seconds, m.similarity) for m in matches] == [
        ("m1", 30.0, 55.0, 0.42)
    ]
    assert pool.recorded[0].parameters == ([0.1], VIDEO_ID, [0.1], 5)
