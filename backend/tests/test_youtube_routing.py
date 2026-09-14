"""Tests that a page URL alone decides which download pipeline a job runs on."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.security import is_youtube_url
from backend.schemas.browser import MediaCandidate, MediaKind
from backend.schemas.video_jobs import CreateVideoJobRequest, JobStatus
from backend.services.video_download.jobs import JobManager

YOUTUBE_URLS = [
    "https://youtube.com/watch?v=x",
    "https://www.youtube.com/watch?v=x",
    "https://m.youtube.com/watch?v=x",
    "https://music.youtube.com/watch?v=x",
    "https://youtu.be/x",
    "https://www.youtube-nocookie.com/embed/x",
    "https://youtube-nocookie.com/embed/x",
]

OTHER_URLS = [
    "https://example.com/watch",
    "https://notyoutube.com/watch",
    "https://youtube.com.evil.example/watch",
    "https://myyoutube.com/watch",
    "https://vimeo.com/1",
]


@pytest.mark.parametrize("url", YOUTUBE_URLS)
def test_youtube_hostnames_are_recognized(url: str) -> None:
    assert is_youtube_url(url) is True


@pytest.mark.parametrize("url", OTHER_URLS)
def test_lookalike_hostnames_are_not_youtube(url: str) -> None:
    assert is_youtube_url(url) is False


def test_a_youtube_page_is_queued_on_the_youtube_pipeline(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    with patch("backend.services.video_download.jobs.validate_remote_url"), patch.object(
        manager._executor, "submit"
    ) as submit:
        job = manager.create(CreateVideoJobRequest(page_url="https://youtu.be/abc"))
    assert job.acquisition_mode == "youtube_pipeline"
    assert job.status == JobStatus.QUEUED
    assert submit.call_args[0][0] == manager._run_youtube


def test_youtube_never_waits_for_a_chrome_download(tmp_path: Path) -> None:
    """Direct candidates must not divert a YouTube page into the browser-download path.

    A YouTube page's media URLs are expiring googlevideo links, so handing one to Chrome
    would strand the job waiting for a download that cannot succeed.
    """
    manager = JobManager(tmp_path)
    request = CreateVideoJobRequest(
        page_url="https://www.youtube.com/watch?v=abc",
        media_candidates=[
            MediaCandidate(kind=MediaKind.DIRECT, url="https://rr1.googlevideo.com/v.mp4")
        ],
    )
    with patch("backend.services.video_download.jobs.validate_remote_url"), patch.object(
        manager._executor, "submit"
    ) as submit:
        job = manager.create(request)
    assert job.acquisition_mode == "youtube_pipeline"
    assert job.status == JobStatus.QUEUED
    assert submit.call_args[0][0] == manager._run_youtube


def test_a_non_youtube_page_still_uses_the_web_pipeline(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    with patch("backend.services.video_download.jobs.validate_remote_url"), patch.object(
        manager._executor, "submit"
    ) as submit:
        job = manager.create(CreateVideoJobRequest(page_url="https://example.com/watch"))
    assert job.acquisition_mode == "companion_download"
    assert submit.call_args[0][0] == manager._run_download
