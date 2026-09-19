"""Tests for stage two: uploading a video and recording it, including its duration."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.download_pipeline.result import RECORD_FAILED, VideoStorageError
from backend.download_pipeline.video_storage import store_video
from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.blob import StoredVideo
from backend.storage.postgres import StoredVideoRecord, VideoRecord

UPLOAD_PATH = "backend.download_pipeline.video_storage.upload_job_video"
RECORD_PATH = "backend.download_pipeline.video_storage.record_job_video"
PROBE_PATH = "backend.download_pipeline.video_storage.probe_media_duration_seconds"

STORED = StoredVideo(
    container="videos", name="videos/job-42/video.mp4", size_bytes=5, content_type="video/mp4"
)

REQUEST = CreateVideoJobRequest(page_url="https://example.com/watch", page_title="Example")

RECORDED = StoredVideoRecord(
    id="11111111-2222-3333-4444-555555555555",
    created_at="2026-09-14T10:00:00+00:00",
    updated_at="2026-09-14T10:00:00+00:00",
    video=VideoRecord(
        source="companion_download",
        source_url=REQUEST.page_url,
        title=REQUEST.page_title,
        blob_container=STORED.container,
        blob_name=STORED.name,
    ),
)


def _acquired(video_path: Path) -> PipelineResult:
    return PipelineResult(
        video_path=video_path,
        transcript_text_path=None,
        transcript_json_path=None,
        transcript_source="page_transcript",
        normalized_transcript=None,
    )


def test_duration_is_probed_before_the_local_copy_is_deleted(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    def fake_upload(*, video_path: Path, job_id: str, progress_callback) -> StoredVideo:
        # `upload_job_video` deletes the local file once it "uploads" it; the probe must
        # have already run by the time this is called, or there is nothing left to read.
        assert video_path.exists()
        video_path.unlink()
        return STORED

    with (
        patch(UPLOAD_PATH, side_effect=fake_upload),
        patch(RECORD_PATH, return_value=RECORDED) as record_mock,
        patch(PROBE_PATH, return_value=754.2) as probe_mock,
    ):
        store_video(
            acquired=_acquired(video_path),
            request=REQUEST,
            job_id="job-42",
            acquisition_mode="companion_download",
            progress_callback=lambda *_: None,
        )

    probe_mock.assert_called_once_with(video_path)
    assert record_mock.call_args.kwargs["duration_seconds"] == 754.2


def test_an_unmeasurable_duration_does_not_stop_the_video_being_stored(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    with (
        patch(UPLOAD_PATH, return_value=STORED),
        patch(RECORD_PATH, return_value=RECORDED) as record_mock,
        patch(PROBE_PATH, return_value=None),
    ):
        outcome = store_video(
            acquired=_acquired(video_path),
            request=REQUEST,
            job_id="job-42",
            acquisition_mode="companion_download",
            progress_callback=lambda *_: None,
        )

    assert outcome.video_id == RECORDED.id
    assert record_mock.call_args.kwargs["duration_seconds"] is None


def test_a_storage_failure_still_raises_even_though_duration_was_already_probed(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    with (
        patch(UPLOAD_PATH, side_effect=OSError("container unreachable")),
        patch(RECORD_PATH) as record_mock,
        patch(PROBE_PATH, return_value=42.0),
    ):
        with pytest.raises(VideoStorageError):
            store_video(
                acquired=_acquired(video_path),
                request=REQUEST,
                job_id="job-42",
                acquisition_mode="companion_download",
                progress_callback=lambda *_: None,
            )

    record_mock.assert_not_called()


def test_a_recording_failure_is_reported_rather_than_raised(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    with (
        patch(UPLOAD_PATH, return_value=STORED),
        patch(RECORD_PATH, side_effect=OSError("database unreachable")),
        patch(PROBE_PATH, return_value=42.0),
    ):
        outcome = store_video(
            acquired=_acquired(video_path),
            request=REQUEST,
            job_id="job-42",
            acquisition_mode="companion_download",
            progress_callback=lambda *_: None,
        )

    assert outcome.video_id is None
    assert outcome.problem == RECORD_FAILED
