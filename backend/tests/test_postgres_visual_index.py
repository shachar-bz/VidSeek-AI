"""Tests for the visual index store: the SQL it sends and what it reads back."""

import pytest

from backend.storage.postgres import (
    KeyframeText,
    NewFrameEmbedding,
    NewVisualSegment,
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


def test_keyframe_text_is_counted() -> None:
    pool = FakePool(rows=[{"text_count": 3}])

    assert PostgresVisualIndex(pool=pool).keyframe_text_count(VIDEO_ID) == 3
    assert "ocr_text is not null" in pool.statements[0]


def test_a_video_with_no_keyframe_text_counts_zero() -> None:
    assert PostgresVisualIndex(pool=FakePool()).keyframe_text_count(VIDEO_ID) == 0


def test_every_keyframe_text_is_scored_by_meaning_with_no_limit() -> None:
    pool = FakePool(
        rows=[
            {"time_seconds": 40.0, "ocr_text": "Load balancer", "similarity": 0.9},
            {"time_seconds": 0.0, "ocr_text": "Agenda", "similarity": 0.8},
        ]
    )

    scored = PostgresVisualIndex(pool=pool).keyframe_text_similarities(VIDEO_ID, [0.4])

    assert [(match.time_seconds, match.similarity) for match in scored] == [(40.0, 0.9), (0.0, 0.8)]
    # The z-score is taken over all of them, so none may be cut off.
    assert "limit" not in pool.statements[0]
    assert "ocr_embedding is not null" in pool.statements[0]


def test_every_keyframe_that_shows_text_is_read_in_time_order() -> None:
    pool = FakePool(
        rows=[
            {"time_seconds": 0.0, "ocr_text": "Agenda"},
            {"time_seconds": 40.0, "ocr_text": "Kafka\nPartitions"},
        ]
    )

    texts = PostgresVisualIndex(pool=pool).keyframe_texts(VIDEO_ID)

    assert [(text.time_seconds, text.text) for text in texts] == [
        (0.0, "Agenda"),
        (40.0, "Kafka\nPartitions"),
    ]
    assert "ocr_text is not null" in pool.statements[0]
    assert "order by time_seconds" in pool.statements[0]
    assert pool.recorded[0].parameters == (VIDEO_ID,)


def test_keyframes_ocr_has_not_read_are_those_with_no_engine() -> None:
    pool = FakePool(rows=[{"unread_count": 4}])
    store = PostgresVisualIndex(pool=pool)

    assert store.unread_keyframe_count(VIDEO_ID) == 4
    assert "ocr_engine is null" in pool.statements[0]
    assert PostgresVisualIndex(pool=FakePool()).unread_keyframe_count(VIDEO_ID) == 0
