"""Tests for the visual stage: who owns the local file, and what each outcome writes.

The indexer is stood in for, so these tests are about the stage's own judgment -- when a video
is handed to the visual executor and when its local copy is deleted instead, and which status
and code each way indexing can end leaves on the `videos` row -- not about SigLIP.
"""

import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend.download_pipeline import visual_indexing
from backend.download_pipeline.visual_indexing import (
    JOB_CANCELLED,
    NO_VIDEO_FRAMES,
    OCR_FAILED,
    OCR_INTERRUPTED,
    VISUAL_INDEXING_DISABLED,
    VISUAL_INDEXING_FAILED,
    VISUAL_INDEXING_INTERRUPTED,
    VISUAL_INDEXING_NOT_SCHEDULED,
    hand_over_for_visual_indexing,
    index_video_visually,
)
from backend.services.visual_indexing import (
    CURRENT_VISUAL_INDEX_VERSION,
    BuiltVisualIndex,
    IndexedFrame,
    KeyframeReading,
    NoFramesToIndex,
    SamplingStopped,
)
from backend.services.visual_indexing.ocr import OcrError, OnScreenText
from backend.services.visual_indexing.segments import SCENE_CHANGE, VIDEO_START, VisualSegment
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
BUILD_PATH = "backend.download_pipeline.visual_indexing.build_visual_index"
PROBE_PATH = "backend.download_pipeline.visual_indexing.probe_media_duration_seconds"

BUILT = BuiltVisualIndex(
    frames=(
        IndexedFrame(time_seconds=0.0, embedding=np.array([1.0, 0.0])),
        IndexedFrame(time_seconds=2.0, embedding=np.array([0.0, 1.0])),
    ),
    segments=(
        VisualSegment(0, 0.0, 2.0, VIDEO_START, (0.0,)),
        VisualSegment(1, 2.0, 4.0, SCENE_CHANGE, (2.0,)),
    ),
    elapsed_seconds=0.1,
)


def local_video(tmp_path: Path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    return path


def status_writes(pool: FakePool) -> list[tuple]:
    """The (status, error) pairs `mark` wrote, in order, and a `ready` for `replace`'s write."""
    writes = []
    for item in pool.recorded:
        if item.statement.startswith("update public.videos set visual_status = %s"):
            writes.append((item.parameters[0], item.parameters[1]))
        elif "set visual_status = 'ready'" in item.statement:
            writes.append(("ready", None))
    return writes


def test_a_stored_video_is_handed_to_the_visual_executor_which_then_owns_its_file(
    tmp_path: Path,
) -> None:
    path = local_video(tmp_path)
    scheduled = []

    hand_over_for_visual_indexing(
        VIDEO_ID,
        path,
        schedule=lambda video_id, local_path: scheduled.append((video_id, local_path)),
        cancel_event=threading.Event(),
        pool=FakePool(),
    )

    assert scheduled == [(VIDEO_ID, path)]
    assert path.exists()


def test_without_a_video_row_the_local_copy_is_deleted_at_once(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()

    hand_over_for_visual_indexing(
        None, path, schedule=lambda *_: None, cancel_event=threading.Event(), pool=pool
    )

    assert not path.exists()
    assert pool.recorded == []


def test_a_cancelled_job_skips_visual_indexing_and_says_why(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    cancelled = threading.Event()
    cancelled.set()
    scheduled = []

    hand_over_for_visual_indexing(
        VIDEO_ID, path, schedule=lambda *args: scheduled.append(args), cancel_event=cancelled, pool=pool
    )

    assert scheduled == []
    assert not path.exists()
    assert status_writes(pool) == [("skipped", JOB_CANCELLED)]


def test_visual_indexing_turned_off_marks_the_video_skipped(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()

    hand_over_for_visual_indexing(
        VIDEO_ID, path, schedule=None, cancel_event=threading.Event(), pool=pool
    )

    assert not path.exists()
    assert status_writes(pool) == [("skipped", VISUAL_INDEXING_DISABLED)]


def test_a_visual_executor_that_refuses_the_task_does_not_leak_the_file(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()

    def refuse(*_):
        raise RuntimeError("cannot schedule new futures after shutdown")

    hand_over_for_visual_indexing(
        VIDEO_ID, path, schedule=refuse, cancel_event=threading.Event(), pool=pool
    )

    assert not path.exists()
    assert status_writes(pool) == [("skipped", VISUAL_INDEXING_NOT_SCHEDULED)]


def test_a_built_index_is_stored_ready_under_the_current_version(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, return_value=BUILT) as build, patch(PROBE_PATH, return_value=4.0):
        outcome = index_video_visually(VIDEO_ID, path, pool=pool)

    assert outcome.status == "ready"
    assert (outcome.frame_count, outcome.segment_count) == (2, 2)
    assert build.call_args.kwargs["duration_seconds"] == 4.0
    assert status_writes(pool) == [("indexing", None), ("ready", None)]
    ready = next(item for item in pool.recorded if "set visual_status = 'ready'" in item.statement)
    assert ready.parameters == (CURRENT_VISUAL_INDEX_VERSION, VIDEO_ID)
    # The index is built from the local copy, which goes once it has been read.
    assert not path.exists()


def test_a_video_with_no_frames_is_skipped_not_failed(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, side_effect=NoFramesToIndex("empty")), patch(PROBE_PATH, return_value=None):
        outcome = index_video_visually(VIDEO_ID, path, pool=pool)

    assert (outcome.status, outcome.problem) == ("skipped", NO_VIDEO_FRAMES)
    assert status_writes(pool)[-1] == ("skipped", NO_VIDEO_FRAMES)
    assert not path.exists()


def test_a_shutdown_mid_index_is_recorded_as_interrupted(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, side_effect=SamplingStopped("stopped")), patch(PROBE_PATH, return_value=None):
        outcome = index_video_visually(VIDEO_ID, path, pool=pool)

    assert (outcome.status, outcome.problem) == ("failed", VISUAL_INDEXING_INTERRUPTED)
    assert not path.exists()


def test_a_failure_never_raises_and_still_deletes_the_local_copy(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, side_effect=RuntimeError("CUDA out of memory")), patch(
        PROBE_PATH, return_value=None
    ):
        outcome = index_video_visually(VIDEO_ID, path, pool=pool)

    assert (outcome.status, outcome.problem) == ("failed", VISUAL_INDEXING_FAILED)
    assert status_writes(pool)[-1] == ("failed", VISUAL_INDEXING_FAILED)
    assert not path.exists()


def test_a_database_that_refuses_the_status_does_not_stop_the_index(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    with (
        patch(BUILD_PATH, return_value=BUILT),
        patch(PROBE_PATH, return_value=4.0),
        patch.object(
            visual_indexing.PostgresVisualIndex, "mark", side_effect=RuntimeError("database down")
        ),
        patch.object(visual_indexing.PostgresVisualIndex, "replace") as replace,
    ):
        outcome = index_video_visually(VIDEO_ID, path, pool=FakePool())

    assert outcome.status == "ready"
    assert replace.called
    assert not path.exists()


# --- on-screen text ------------------------------------------------------------------------

READ_TEXT_PATH = "backend.download_pipeline.visual_indexing.read_keyframe_text"


class NamedEngine:
    name = "surya-ocr-2"

    def read(self, images):
        raise AssertionError("read_keyframe_text is stood in for")


def text_writes(pool: FakePool) -> list:
    """Every keyframe row `set_keyframe_text` wrote, in order."""
    return [
        row
        for item in pool.recorded
        if item.statement.lstrip().startswith("update public.video_keyframes")
        for row in item.parameters
    ]


def batches(*groups):
    """What `read_keyframe_text` yields: lists of readings, one list per batch."""
    return iter([list(group) for group in groups])


def test_keyframe_text_is_read_after_the_index_is_ready_and_stored_batch_by_batch(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    order = []
    slide = OnScreenText("System design", "en", 0.9)

    def read(local_path, keyframe_times, engine, *, stop_event):
        order.append(("read", status_writes(pool)[-1][0], local_path.exists(), list(keyframe_times)))
        return batches([KeyframeReading(0.0, slide)], [KeyframeReading(2.0, None)])

    with patch(BUILD_PATH, return_value=BUILT), patch(PROBE_PATH, return_value=4.0), patch(
        READ_TEXT_PATH, side_effect=read
    ):
        outcome = index_video_visually(
            VIDEO_ID,
            path,
            pool=pool,
            ocr_engine=NamedEngine(),
            embed_texts=lambda texts: [[0.5, 0.5] for _ in texts],
        )

    # Read once the index is ready, from the local copy, which is deleted only afterwards.
    assert order == [("read", "ready", True, [0.0, 2.0])]
    assert not path.exists()
    assert text_writes(pool) == [
        ("System design", "en", 0.9, [0.5, 0.5], "surya-ocr-2", VIDEO_ID, 0.0),
        (None, None, None, None, "surya-ocr-2", VIDEO_ID, 2.0),
    ]
    assert (outcome.status, outcome.keyframes_read, outcome.keyframes_with_text) == ("ready", 2, 1)
    assert outcome.ocr_problem is None


def test_without_an_ocr_engine_the_keyframes_are_left_unread(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, return_value=BUILT), patch(PROBE_PATH, return_value=4.0), patch(
        READ_TEXT_PATH
    ) as read:
        outcome = index_video_visually(VIDEO_ID, path, pool=pool)

    assert not read.called
    assert text_writes(pool) == []
    assert (outcome.status, outcome.keyframes_read, outcome.ocr_problem) == ("ready", 0, None)


def test_an_ocr_failure_keeps_the_index_ready_and_what_was_read_before_it(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()

    def read(local_path, keyframe_times, engine, *, stop_event):
        yield [KeyframeReading(0.0, OnScreenText("Agenda", "en", 0.8))]
        raise OcrError("Surya's worker exited")

    with patch(BUILD_PATH, return_value=BUILT), patch(PROBE_PATH, return_value=4.0), patch(
        READ_TEXT_PATH, side_effect=read
    ):
        outcome = index_video_visually(
            VIDEO_ID, path, pool=pool, ocr_engine=NamedEngine(), embed_texts=lambda texts: [[1.0]]
        )

    assert (outcome.status, outcome.ocr_problem, outcome.keyframes_read) == ("ready", OCR_FAILED, 1)
    assert status_writes(pool)[-1] == ("ready", None)
    assert [row[0] for row in text_writes(pool)] == ["Agenda"]
    assert not path.exists()


def test_a_shutdown_while_reading_text_leaves_the_index_ready(tmp_path: Path) -> None:
    path = local_video(tmp_path)
    pool = FakePool()
    with patch(BUILD_PATH, return_value=BUILT), patch(PROBE_PATH, return_value=4.0), patch(
        READ_TEXT_PATH, side_effect=SamplingStopped("stopped")
    ):
        outcome = index_video_visually(VIDEO_ID, path, pool=pool, ocr_engine=NamedEngine())

    assert (outcome.status, outcome.problem, outcome.ocr_problem) == ("ready", None, OCR_INTERRUPTED)
    assert status_writes(pool)[-1] == ("ready", None)
    assert not path.exists()
