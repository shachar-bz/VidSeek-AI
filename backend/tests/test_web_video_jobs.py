"""Tests for authenticated download job lifecycle decisions."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.Web_video_download.downloader import UnsupportedMediaError
from backend.Web_video_download.jobs import JobManager
from backend.Web_video_download.models import (
    BrowserContext,
    BrowserCookie,
    CreateVideoJobRequest,
    JobStatus,
    MediaCandidate,
    MediaKind,
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
        with patch("backend.Web_video_download.jobs.validate_remote_url"):
            job = manager.create(direct_request())
        assert job.status == JobStatus.AWAITING_BROWSER_DOWNLOAD
        assert job.acquisition_mode == "browser_download"
    finally:
        manager.shutdown()


def test_cancel_discards_browser_secrets(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.Web_video_download.jobs.validate_remote_url"):
            created = manager.create(direct_request())
        cancelled = manager.cancel(created.job_id)
        assert cancelled.status == JobStatus.CANCELLED
        assert manager._jobs[created.job_id].request.browser_context.cookies == []
    finally:
        manager.shutdown()


def test_drm_is_rejected_before_job_creation(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.Web_video_download.jobs.validate_remote_url"):
            with pytest.raises(UnsupportedMediaError, match="DRM"):
                manager.create(direct_request(drm_detected=True))
    finally:
        manager.shutdown()
