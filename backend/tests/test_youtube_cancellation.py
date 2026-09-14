"""Tests that cancelling a YouTube job actually stops it.

Before the route was wired up the YouTube pipeline had no cancellation at all: it ran as
one blocking call with no progress hooks, so POST /cancel would have returned a promise
the backend could not keep.
"""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from yt_dlp.utils import DownloadCancelled

from backend.services.video_download.youtube import pipeline
from backend.services.video_download.youtube.downloader import (
    DownloadedVideo,
    build_download_options,
)


def test_hooks_are_installed_even_though_console_progress_is_off() -> None:
    """`noprogress` silences yt-dlp's own rendering; it does not disable hooks."""
    def hook(_: dict) -> None:
        return None

    options = build_download_options(Path("out"), progress_hooks=[hook])
    assert options["noprogress"] is True
    assert options["progress_hooks"] == [hook]


def test_the_cli_path_installs_no_hooks() -> None:
    assert "progress_hooks" not in build_download_options(Path("out"))


def test_cancelling_before_the_download_starts_downloads_nothing() -> None:
    cancel_event = threading.Event()
    cancel_event.set()
    with patch.object(pipeline, "download_video") as download:
        with pytest.raises(DownloadCancelled):
            pipeline.download_youtube_video(
                "https://youtu.be/abc", output_dir="out", cancel_event=cancel_event
            )
    download.assert_not_called()


def test_cancelling_mid_download_aborts_from_inside_the_hook(tmp_path: Path) -> None:
    """The hook is what makes a long download interruptible rather than merely abandoned."""
    cancel_event = threading.Event()

    def fake_download(url, output_dir, *, progress_hooks=None):
        cancel_event.set()
        # yt-dlp calls the hook as bytes arrive; raising from it is how a download stops.
        for hook in progress_hooks or []:
            hook({"downloaded_bytes": 1, "total_bytes": 100})
        raise AssertionError("the hook should have aborted the download")

    with patch.object(pipeline, "download_video", side_effect=fake_download):
        with pytest.raises(DownloadCancelled):
            pipeline.download_youtube_video(
                "https://youtu.be/abc", output_dir=str(tmp_path), cancel_event=cancel_event
            )


def test_cancelling_after_the_download_writes_no_transcript(tmp_path: Path) -> None:
    cancel_event = threading.Event()

    def fake_download(url, output_dir, *, progress_hooks=None):
        cancel_event.set()
        return DownloadedVideo(video_id="abc", title="A", video_path=str(tmp_path / "abc.mp4"))

    with patch.object(pipeline, "download_video", side_effect=fake_download), patch.object(
        pipeline, "_build_transcript"
    ) as build:
        with pytest.raises(DownloadCancelled):
            pipeline.download_youtube_video(
                "https://youtu.be/abc", output_dir=str(tmp_path), cancel_event=cancel_event
            )
    build.assert_not_called()
    assert not (tmp_path / "abc.transcript.txt").exists()


def test_progress_is_reported_as_a_fraction_of_the_download(tmp_path: Path) -> None:
    seen: list[dict] = []

    def fake_download(url, output_dir, *, progress_hooks=None):
        for hook in progress_hooks or []:
            hook({"downloaded_bytes": 50, "total_bytes": 100})
        return DownloadedVideo(video_id="abc", title="A", video_path=str(tmp_path / "abc.mp4"))

    with patch.object(pipeline, "download_video", side_effect=fake_download), patch.object(
        pipeline, "_build_transcript"
    ) as build, patch.object(pipeline, "_write_comments", return_value=([], None)):
        build.return_value = pipeline.YouTubeTranscript(source="youtube_captions", text="x")
        pipeline.download_youtube_video(
            "https://youtu.be/abc",
            output_dir=str(tmp_path),
            progress_hook=seen.append,
        )
    assert seen == [{"downloaded_bytes": 50, "total_bytes": 100}]
