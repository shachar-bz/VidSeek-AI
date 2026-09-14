"""Tests for authenticated download job lifecycle decisions."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.errors import UnsupportedMediaError
from backend.schemas.browser import (
    BrowserContext,
    BrowserCookie,
    MediaCandidate,
    MediaKind,
)
from backend.schemas.video_jobs import (
    BrowserDownloadCompleteRequest,
    CreateVideoJobRequest,
    JobStatus,
)
from backend.services.video_download.jobs import JobManager
from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.r2 import StoredVideo

STORED = StoredVideo(
    bucket="vidseek-videos",
    key="videos/job-42/video.mp4",
    size_bytes=5,
    content_type="video/mp4",
)


def direct_request(**overrides) -> CreateVideoJobRequest:
    values = {
        "page_url": "https://example.com/watch",
        "page_title": "Example",
        "media_candidates": [
            MediaCandidate(kind=MediaKind.DIRECT, url="https://cdn.example.com/video.mp4")
        ],
        "browser_context": BrowserContext(
            cookies=[BrowserCookie(name="session", value="secret", domain=".example.com")]
        ),
    }
    values.update(overrides)
    return CreateVideoJobRequest(**values)


def test_direct_file_waits_for_cookie_aware_chrome_download(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.services.video_download.jobs.validate_remote_url"):
            job = manager.create(direct_request())
        assert job.status == JobStatus.AWAITING_BROWSER_DOWNLOAD
        assert job.acquisition_mode == "browser_download"
    finally:
        manager.shutdown()


def test_cancel_discards_browser_secrets(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.services.video_download.jobs.validate_remote_url"):
            created = manager.create(direct_request())
        cancelled = manager.cancel(created.job_id)
        assert cancelled.status == JobStatus.CANCELLED
        assert manager._jobs[created.job_id].request.browser_context.cookies == []
    finally:
        manager.shutdown()


def test_drm_is_rejected_before_job_creation(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.services.video_download.jobs.validate_remote_url"):
            with pytest.raises(UnsupportedMediaError, match="DRM"):
                manager.create(direct_request(drm_detected=True))
    finally:
        manager.shutdown()


def run_to_completion(manager: JobManager, download_root: Path, **upload):
    """Drive one job from a Chrome download through to its recorded result.

    The file Chrome "downloaded" is the shortest way into the pipeline that still goes
    through the job manager's own completion path, which is what the upload hangs off.
    """
    video_path = download_root / "video.mp4"
    video_path.write_bytes(b"video")
    result = PipelineResult(
        video_path=video_path,
        transcript_text_path=None,
        transcript_json_path=None,
        transcript_source="page_transcript",
    )
    with patch("backend.services.video_download.jobs.validate_remote_url"):
        created = manager.create(direct_request())
    with (
        # ffprobe is not on every machine, and the stand-in file has no video stream for
        # it to find anyway; what is under test starts once the file is accepted.
        patch(
            "backend.services.video_download.jobs.validate_local_media_path",
            return_value=video_path,
        ),
        patch("backend.services.video_download.jobs.process_downloaded_video", return_value=result),
        patch("backend.services.video_download.jobs.upload_job_video", **upload),
    ):
        manager.complete_browser_download(
            created.job_id, BrowserDownloadCompleteRequest(local_path=str(video_path))
        )
        manager._executor.shutdown(wait=True)
    return manager.get(created.job_id)


def test_a_finished_job_reports_where_its_video_was_stored(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(manager, tmp_path, return_value=STORED)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.COMPLETE
    assert job.video_storage_key == STORED.key
    assert job.video_path == str(tmp_path / "video.mp4")


def test_a_job_with_no_bucket_configured_still_completes(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(manager, tmp_path, return_value=None)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.COMPLETE
    assert job.video_storage_key is None


def test_an_unreachable_bucket_costs_the_job_its_durability_not_its_result(
    tmp_path: Path,
) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(manager, tmp_path, side_effect=OSError("bucket unreachable"))
    finally:
        manager.shutdown()

    # The video and its transcript are on disk either way, so the job reports what it has
    # rather than throwing the work away because the last step failed.
    assert job.status == JobStatus.PARTIAL_SUCCESS
    assert job.error_code == "upload_failed"
    assert job.video_path == str(tmp_path / "video.mp4")
    assert job.video_storage_key is None
