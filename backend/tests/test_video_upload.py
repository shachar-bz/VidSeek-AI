"""Tests for the upload step a finished job runs before it reports its result."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.schemas.video_jobs import JobPhase
from backend.services.video_download import video_upload
from backend.storage.r2 import StoredVideo

STORED = StoredVideo(
    bucket="vidseek-videos",
    key="videos/job-42/clip.mp4",
    size_bytes=11,
    content_type="video/mp4",
)


class FakeVideoStorage:
    """Stands in for the bucket, and reports progress the way boto3 does."""

    def __init__(self, chunks: tuple[tuple[int, int], ...] = ((5, 10), (10, 10))):
        self.chunks = chunks
        self.uploaded: list[tuple[Path, str]] = []

    def upload_video(self, local_path, *, video_id, progress_callback=None):
        self.uploaded.append((local_path, video_id))
        for uploaded, total in self.chunks:
            if progress_callback is not None:
                progress_callback(uploaded, total)
        return STORED


def _upload(tmp_path: Path, storage: FakeVideoStorage, *, configured: bool = True):
    reported: list[tuple[JobPhase, float, str]] = []
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video-bytes")
    with (
        patch.object(video_upload, "is_r2_configured", return_value=configured),
        patch.object(video_upload, "R2VideoStorage", return_value=storage),
    ):
        stored = video_upload.upload_job_video(
            video_path=video_path,
            job_id="job-42",
            progress_callback=lambda phase, value, message: reported.append(
                (phase, value, message)
            ),
        )
    return stored, reported


def test_the_video_is_stored_under_the_job_that_produced_it(tmp_path: Path) -> None:
    storage = FakeVideoStorage()
    stored, _ = _upload(tmp_path, storage)

    assert stored == STORED
    assert storage.uploaded[0][1] == "job-42"


def test_without_a_bucket_the_video_is_left_alone_rather_than_the_job_failing(
    tmp_path: Path,
) -> None:
    storage = FakeVideoStorage()
    stored, reported = _upload(tmp_path, storage, configured=False)

    assert stored is None
    assert storage.uploaded == []
    assert reported == []


def test_upload_progress_stays_inside_the_slice_of_the_bar_it_owns(tmp_path: Path) -> None:
    _, reported = _upload(tmp_path, FakeVideoStorage())

    assert {phase for phase, _, _ in reported} == {JobPhase.UPLOAD}
    values = [value for _, value, _ in reported]
    assert values == sorted(values)
    assert values[0] == pytest.approx(video_upload.PROGRESS_START)
    assert values[-1] == pytest.approx(video_upload.PROGRESS_END)


def test_an_empty_file_does_not_divide_its_progress_by_zero(tmp_path: Path) -> None:
    # boto3 reports a total of zero bytes for an empty file; a job should still finish.
    _, reported = _upload(tmp_path, FakeVideoStorage(chunks=((0, 0),)))

    assert reported[-1][1] == pytest.approx(video_upload.PROGRESS_END)
