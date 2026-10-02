"""Tests for how a visual index a shutdown interrupted gets built again.

A shutdown stops an index part-way, or cancels one still queued, and either way the local
video file is gone. These tests check that both leave the video marked interrupted, that the
store hands each interrupted video to one caller only, that the stage fetches the stored copy
back from Blob Storage and indexes it from the start, and that the job manager does this for
every interrupted video when it starts.
"""

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.download_pipeline.visual_indexing import (
    VISUAL_INDEXING_INTERRUPTED,
    claim_interrupted_visual_indexing,
    reindex_video_visually,
)
from backend.services.video_download.jobs import JobManager
from backend.tests.fake_postgres import FakePool
from backend.tests.test_visual_indexing_stage import BUILD_PATH, BUILT, PROBE_PATH, status_writes

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
OTHER_VIDEO_ID = "66666666-7777-8888-9999-000000000000"
BLOB_NAME = "videos/abc/lecture.mp4"
RECORDS_PATH = "backend.download_pipeline.visual_indexing.PostgresVideoRecords"
JOBS = "backend.services.video_download.jobs"


class FakeBlobStorage:
    """Writes a stand-in video wherever it is asked to, or fails when told to."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.downloads: list[tuple[str, Path]] = []

    def download_video(self, name: str, destination: Path) -> Path:
        self.downloads.append((name, destination))
        if self.fail:
            destination.write_bytes(b"half a vid")
            raise ConnectionError("network unreachable")
        destination.write_bytes(b"video")
        return destination


def recorded_video():
    return patch(RECORDS_PATH, return_value=SimpleNamespace(
        get_by_id=lambda _: SimpleNamespace(video=SimpleNamespace(blob_name=BLOB_NAME))
    ))


def test_claiming_moves_interrupted_videos_back_to_pending_in_one_statement() -> None:
    pool = FakePool(rows=[{"id": VIDEO_ID}, {"id": OTHER_VIDEO_ID}])

    claimed = claim_interrupted_visual_indexing(pool=pool)

    assert claimed == [VIDEO_ID, OTHER_VIDEO_ID]
    [statement] = pool.recorded
    assert "set visual_status = 'pending', visual_error = null" in statement.statement
    assert "where visual_status = 'failed' and visual_error = %s" in statement.statement
    assert "returning id" in statement.statement
    assert statement.parameters == (VISUAL_INDEXING_INTERRUPTED,)


def test_an_interrupted_video_is_fetched_from_blob_storage_and_indexed_from_the_start(
    tmp_path: Path,
) -> None:
    pool = FakePool()
    blob = FakeBlobStorage()
    seen = {}

    def build(local_path, **_):
        seen["path"] = local_path
        seen["bytes"] = local_path.read_bytes()
        return BUILT

    with recorded_video(), patch(BUILD_PATH, side_effect=build), patch(PROBE_PATH, return_value=4.0):
        outcome = reindex_video_visually(VIDEO_ID, tmp_path, pool=pool, blob_storage=blob)

    assert outcome.status == "ready"
    [(name, destination)] = blob.downloads
    assert name == BLOB_NAME
    # Indexed from the downloaded copy, which keeps the stored video's extension.
    assert seen == {"path": destination, "bytes": b"video"}
    assert destination.parent == tmp_path and destination.suffix == ".mp4"
    assert status_writes(pool) == [("indexing", None), ("ready", None)]
    assert list(tmp_path.iterdir()) == []


def test_a_video_that_cannot_be_fetched_stays_interrupted_for_the_next_start(tmp_path: Path) -> None:
    pool = FakePool()

    with recorded_video(), patch(BUILD_PATH) as build:
        outcome = reindex_video_visually(
            VIDEO_ID, tmp_path, pool=pool, blob_storage=FakeBlobStorage(fail=True)
        )

    assert (outcome.status, outcome.problem) == ("failed", VISUAL_INDEXING_INTERRUPTED)
    assert not build.called
    assert status_writes(pool) == [("failed", VISUAL_INDEXING_INTERRUPTED)]
    # The half-written download does not stay behind.
    assert list(tmp_path.iterdir()) == []


def test_a_reindex_reached_after_shutdown_began_does_not_download_anything(tmp_path: Path) -> None:
    pool = FakePool()
    blob = FakeBlobStorage()
    stopped = threading.Event()
    stopped.set()

    outcome = reindex_video_visually(
        VIDEO_ID, tmp_path, stop_event=stopped, pool=pool, blob_storage=blob
    )

    assert (outcome.status, outcome.problem) == ("failed", VISUAL_INDEXING_INTERRUPTED)
    assert blob.downloads == []
    assert status_writes(pool) == [("failed", VISUAL_INDEXING_INTERRUPTED)]


def test_on_start_every_claimed_video_is_reindexed_on_the_visual_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    monkeypatch.setenv("AZURE_DATABASE_URL", "postgresql://unused")
    reindexed = []
    both_ran = threading.Event()

    def reindex(video_id, work_directory, *, stop_event, ocr_engine):
        reindexed.append((video_id, work_directory, threading.current_thread().name))
        if len(reindexed) == 2:
            both_ran.set()

    manager = JobManager(tmp_path)
    try:
        with (
            patch(f"{JOBS}.claim_interrupted_visual_indexing", return_value=[VIDEO_ID, OTHER_VIDEO_ID]),
            patch(f"{JOBS}.reindex_video_visually", side_effect=reindex),
        ):
            manager.resume_interrupted_visual_indexing()
            # The claim queues the videos itself, so the executor is shut only once they ran.
            assert both_ran.wait(timeout=10)
    finally:
        manager.shutdown()

    assert [video_id for video_id, _, _ in reindexed] == [VIDEO_ID, OTHER_VIDEO_ID]
    assert all(directory == tmp_path / "visual-queue" for _, directory, _ in reindexed)
    assert all(thread.startswith("vidseek-visual") for _, _, thread in reindexed)


@pytest.mark.parametrize(
    "setting, value",
    [("VIDSEEK_VISUAL_INDEXING", "false"), ("AZURE_DATABASE_URL", "")],
)
def test_on_start_nothing_is_claimed_without_visual_indexing_or_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str, value: str
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    monkeypatch.setenv("AZURE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv(setting, value)

    manager = JobManager(tmp_path)
    try:
        with patch(f"{JOBS}.claim_interrupted_visual_indexing") as claim:
            manager.resume_interrupted_visual_indexing()
            manager._visual_executor.shutdown(wait=True)
    finally:
        manager.shutdown()

    assert not claim.called


def test_a_database_that_fails_the_claim_does_not_break_the_visual_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    monkeypatch.setenv("AZURE_DATABASE_URL", "postgresql://unused")

    manager = JobManager(tmp_path)
    try:
        with (
            patch(f"{JOBS}.claim_interrupted_visual_indexing", side_effect=OSError("database down")),
            patch(f"{JOBS}.reindex_video_visually") as reindex,
        ):
            manager.resume_interrupted_visual_indexing()
            still_runs = manager._visual_executor.submit(lambda: "ran")
            assert still_runs.result(timeout=10) == "ran"
    finally:
        manager.shutdown()

    assert not reindex.called


def test_a_claimed_video_the_manager_shut_down_before_reindexing_is_marked_interrupted_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    monkeypatch.setenv("AZURE_DATABASE_URL", "postgresql://unused")
    started = threading.Event()
    release = threading.Event()

    def occupy_the_worker(video_id, *_, **__):
        started.set()
        release.wait(timeout=10)

    manager = JobManager(tmp_path)
    with (
        patch(f"{JOBS}.claim_interrupted_visual_indexing", return_value=[VIDEO_ID, OTHER_VIDEO_ID]),
        patch(f"{JOBS}.reindex_video_visually", side_effect=occupy_the_worker),
        patch(f"{JOBS}.mark_visual_indexing_never_run") as mark_never_run,
    ):
        manager.resume_interrupted_visual_indexing()
        assert started.wait(timeout=10)
        manager.shutdown()
        release.set()
        manager._visual_executor.shutdown(wait=True)

    # The first was running when the manager shut down, and marks itself; the second never ran.
    assert [call.args for call in mark_never_run.call_args_list] == [(OTHER_VIDEO_ID,)]
