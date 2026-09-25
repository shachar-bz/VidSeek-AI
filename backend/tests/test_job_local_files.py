"""Tests that a job leaves no local files behind, however its run ends.

Each run writes into its own `jobs/<job_id>` workspace under the download root, and the job
manager deletes the workspace when the run ends. These tests end runs every way they can
end -- finished, upload refused, cancelled during the download or the transcript, a
download that failed partway, a Chrome file that could not be processed -- and check that
nothing the run wrote is still on disk afterwards, while a new manager clears whatever a
killed process left.
"""

import threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yt_dlp.utils import DownloadCancelled

from backend.schemas.browser import BrowserContext, MediaCandidate, MediaKind
from backend.schemas.video_jobs import (
    BrowserDownloadCompleteRequest,
    CreateVideoJobRequest,
    JobStatus,
)
from backend.services.video_download.jobs import JobManager
from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.blob import StoredVideo

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
STORED = StoredVideo(
    container="videos", name="videos/job-42/video.mp4", size_bytes=5, content_type="video/mp4"
)
ACQUISITION = "backend.download_pipeline.acquisition"
STORAGE = "backend.download_pipeline.video_storage"
# What every run here stands in for: no database row, and no ffprobe on the stand-in file.
STORAGE_DEFAULTS = {
    f"{STORAGE}.record_job_video": {"return_value": None},
    f"{STORAGE}.probe_media_duration_seconds": {"return_value": None},
}


def _request(page_url: str, kind: MediaKind) -> CreateVideoJobRequest:
    return CreateVideoJobRequest(
        page_url=page_url,
        page_title="Example",
        media_candidates=[MediaCandidate(kind=kind, url="https://cdn.example.com/video.m3u8")],
        browser_context=BrowserContext(),
    )


def _write_beside(video_path: Path) -> PipelineResult:
    """Write the files a real acquisition leaves beside its video, and describe them."""
    video_path.write_bytes(b"video")
    text_path = video_path.with_suffix(".transcript.txt")
    json_path = video_path.with_suffix(".transcript.json")
    text_path.write_text("hello", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")
    video_path.with_name(f"{video_path.stem}.en.vtt").write_text("WEBVTT", encoding="utf-8")
    return PipelineResult(
        video_path=video_path,
        transcript_text_path=text_path,
        transcript_json_path=json_path,
        transcript_source="captions",
        transcript_error=None,
        normalized_transcript=None,
    )


def _files_under(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file())


def _patched(stack: ExitStack, mocks: dict[str, dict]) -> None:
    for target, mock in (STORAGE_DEFAULTS | mocks).items():
        stack.enter_context(patch(target, **mock))


def _run_companion_job(manager: JobManager, page_url: str, acquisition: str, effect) -> str:
    """Start a job the companion downloads itself, and wait for its run to end."""
    with ExitStack() as stack:
        _patched(
            stack,
            {
                "backend.services.video_download.jobs.validate_remote_url": {},
                f"{STORAGE}.upload_job_video": {"return_value": STORED},
                f"{ACQUISITION}.{acquisition}": {"side_effect": effect},
            },
        )
        created = manager.create(_request(page_url, MediaKind.HLS))
        manager._executor.shutdown(wait=True)
    return created.job_id


def _run_chrome_job(
    manager: JobManager, download_root: Path, mocks: dict[str, dict]
) -> tuple[str, Path]:
    """Hand the manager a file Chrome downloaded, and wait for its run to end."""
    chrome_file = download_root / "video.mp4"
    chrome_file.write_bytes(b"video")
    with patch("backend.services.video_download.jobs.validate_remote_url"):
        created = manager.create(_request("https://example.com/watch", MediaKind.DIRECT))
    with ExitStack() as stack:
        _patched(
            stack,
            {
                "backend.services.video_download.jobs.validate_local_media_path": {
                    "return_value": chrome_file
                },
            }
            | mocks,
        )
        manager.complete_browser_download(
            created.job_id, BrowserDownloadCompleteRequest(local_path=str(chrome_file))
        )
        manager._executor.shutdown(wait=True)
    return created.job_id, chrome_file


def _processed_beside_the_video(*, video, **_) -> PipelineResult:
    return _write_beside(video.video_path)


def test_a_finished_job_deletes_its_video_and_everything_written_beside_it(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job_id, chrome_file = _run_chrome_job(
            manager,
            tmp_path,
            {
                f"{ACQUISITION}.process_downloaded_video": {"side_effect": _processed_beside_the_video},
                f"{STORAGE}.upload_job_video": {"return_value": STORED},
            },
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.COMPLETE
    assert not chrome_file.exists()
    assert _files_under(tmp_path) == []
    # Nothing the extension is told about points at a file that no longer exists.
    assert (job.video_path, job.transcript_text_path, job.transcript_json_path) == (None, None, None)


def test_a_refused_upload_deletes_the_video_and_its_thumbnail(tmp_path: Path) -> None:
    def refuse_after_the_thumbnail(*, video_path, **_):
        video_path.with_name(f"{video_path.stem}.thumbnail.jpg").write_bytes(b"jpeg")
        raise OSError("container unreachable")

    manager = JobManager(tmp_path)
    try:
        job_id, _ = _run_chrome_job(
            manager,
            tmp_path,
            {
                f"{ACQUISITION}.process_downloaded_video": {"side_effect": _processed_beside_the_video},
                f"{STORAGE}.upload_job_video": {
                    "side_effect": refuse_after_the_thumbnail
                },
            },
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.FAILED
    assert job.error_code == "upload_failed"
    assert _files_under(tmp_path) == []


def test_a_cancel_during_the_transcript_deletes_the_chrome_download(tmp_path: Path) -> None:
    def cancelled_while_transcribing(*, video, **_):
        _write_beside(video.video_path)
        raise DownloadCancelled("Job cancelled")

    manager = JobManager(tmp_path)
    try:
        job_id, chrome_file = _run_chrome_job(
            manager,
            tmp_path,
            {f"{ACQUISITION}.process_downloaded_video": {"side_effect": cancelled_while_transcribing}},
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.CANCELLED
    assert not chrome_file.exists()
    assert _files_under(tmp_path) == []


def test_a_chrome_download_that_cannot_be_processed_fails_and_is_deleted(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job_id, chrome_file = _run_chrome_job(
            manager,
            tmp_path,
            {f"{ACQUISITION}.process_downloaded_video": {"side_effect": RuntimeError("unreadable")}},
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    # Nothing was stored, so nothing is claimed as kept.
    assert job.status == JobStatus.FAILED
    assert job.error_code == "processing_failed"
    assert job.video_path is None
    assert not chrome_file.exists()


def test_a_chrome_download_whose_job_was_cancelled_before_it_ran_is_deleted(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        with patch("backend.services.video_download.jobs.validate_remote_url"):
            created = manager.create(_request("https://example.com/watch", MediaKind.DIRECT))
        chrome_file = tmp_path / "video.mp4"
        chrome_file.write_bytes(b"video")
        manager.cancel(created.job_id)
        manager._run(created.job_id, can_capture_on_failure=False, local_path=chrome_file)
    finally:
        manager.shutdown()

    assert not chrome_file.exists()


def test_a_cancelled_companion_download_leaves_no_partial_files(tmp_path: Path) -> None:
    seen = {}

    def cancelled_partway(*, download_root, **_):
        seen["download_root"] = download_root
        (download_root / "video.mp4.part").write_bytes(b"half")
        (download_root / "video.mp4.part-Frag3").write_bytes(b"fragment")
        raise DownloadCancelled("Download cancelled")

    manager = JobManager(tmp_path)
    try:
        job_id = _run_companion_job(
            manager, "https://example.com/watch", "download_and_transcribe", cancelled_partway
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.CANCELLED
    # The download ran in the job's own workspace, not in the download root itself.
    assert seen["download_root"] == tmp_path / "jobs" / job_id
    assert _files_under(tmp_path) == []


def test_a_youtube_download_that_fails_partway_leaves_no_partial_files(tmp_path: Path) -> None:
    def failed_partway(*, download_root, **_):
        (download_root / "abc.mp4.part").write_bytes(b"half")
        (download_root / "abc.en.vtt").write_text("WEBVTT", encoding="utf-8")
        (download_root / "abc.comments.json").write_text("[]", encoding="utf-8")
        raise RuntimeError("connection reset")

    manager = JobManager(tmp_path)
    try:
        job_id = _run_companion_job(
            manager, "https://www.youtube.com/watch?v=abc", "run_youtube_job", failed_partway
        )
        job = manager.get(job_id)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.FAILED
    assert job.error_code == "download_failed"
    assert _files_under(tmp_path) == []


def test_a_new_manager_clears_what_a_killed_process_left_and_nothing_else(tmp_path: Path) -> None:
    left_in_a_workspace = tmp_path / "jobs" / "dead-job" / "video.mp4.part"
    left_in_the_visual_queue = tmp_path / "visual-queue" / "queued.mp4"
    chrome_saving_into_the_root = tmp_path / "video.mp4.crdownload"
    transcript_store_file = tmp_path / "transcripts" / "video.json"
    for path in (
        left_in_a_workspace,
        left_in_the_visual_queue,
        chrome_saving_into_the_root,
        transcript_store_file,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    JobManager(tmp_path).shutdown()

    assert not (tmp_path / "jobs" / "dead-job").exists()
    assert not left_in_the_visual_queue.exists()
    assert chrome_saving_into_the_root.exists()
    assert transcript_store_file.exists()


def test_a_video_handed_to_visual_indexing_outlives_its_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    workspace_deleted = threading.Event()
    seen = {}

    def index(video_id, local_path, *, stop_event, ocr_engine):
        # Runs only once the job's run, and with it the workspace, is finished.
        workspace_deleted.wait(timeout=10)
        seen.update(path=local_path, existed=local_path.exists())
        local_path.unlink()

    manager = JobManager(tmp_path)
    try:
        with patch("backend.services.video_download.jobs.index_video_visually", side_effect=index):
            # No timed transcript, so the run stops right after Store and the hand-over.
            job_id, _ = _run_chrome_job(
                manager,
                tmp_path,
                {
                    f"{ACQUISITION}.process_downloaded_video": {
                        "side_effect": _processed_beside_the_video
                    },
                    f"{STORAGE}.upload_job_video": {"return_value": STORED},
                    f"{STORAGE}.record_job_video": {"return_value": SimpleNamespace(id=VIDEO_ID)},
                },
            )
            assert not (tmp_path / "jobs" / job_id).exists()
            workspace_deleted.set()
            manager._visual_executor.shutdown(wait=True)
    finally:
        manager.shutdown()

    assert seen["path"].parent == tmp_path / "visual-queue"
    assert seen["existed"] is True
    assert _files_under(tmp_path) == []
