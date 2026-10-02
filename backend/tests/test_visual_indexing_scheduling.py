"""Tests for how a stored video reaches visual indexing: the pipeline's hand-over and the executor.

The job manager runs visual indexing on a second single-worker executor, so a job's slot is
free once its transcript stages end while two indexing runs never share the GPU. These tests
check the hand-over happens right after Store, that the task runs on the visual executor and
owns the local file, and that a task the manager never got to still does not leak the file
and is marked interrupted.
"""

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.core import config
from backend.download_pipeline import AcquisitionRoute
from backend.download_pipeline.embedding import EmbeddedVideo
from backend.download_pipeline.insights import InsightGenerationOutcome
from backend.download_pipeline.pipeline import run_download_pipeline
from backend.download_pipeline.segmentation import SegmentedVideo
from backend.download_pipeline.video_storage import StorageOutcome
from backend.schemas.browser import BrowserContext, MediaCandidate, MediaKind
from backend.schemas.video_jobs import BrowserDownloadCompleteRequest, CreateVideoJobRequest
from backend.services.transcripts import NormalizedTranscript, TimingFidelity, TranscriptSegment
from backend.services.video_download.jobs import JobManager
from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.blob import StoredVideo
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
STORED = StoredVideo(
    container="videos", name="videos/job-42/video.mp4", size_bytes=5, content_type="video/mp4"
)
TRANSCRIPT = NormalizedTranscript(
    source="captions",
    timing_fidelity=TimingFidelity.CAPTION,
    segments=[TranscriptSegment(index=0, start_seconds=0.0, end_seconds=1.0, text="hello")],
)
INDEX_PATH = "backend.services.video_download.jobs.index_video_visually"


def acquired(video_path: Path, transcript=None) -> PipelineResult:
    return PipelineResult(
        video_path=video_path,
        transcript_text_path=None,
        transcript_json_path=None,
        transcript_source="captions",
        transcript_error=None,
        normalized_transcript=transcript,
    )


def test_the_hand_over_happens_after_store_and_before_the_transcript_stages(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    order: list[str] = []

    def stage(name, value):
        def run(*_, **__):
            order.append(name)
            return value

        return run

    def hand_over(video_id, local_path, *, schedule, cancel_event, pool):
        order.append("visual")
        assert (video_id, local_path) == (VIDEO_ID, video_path)
        assert schedule is scheduler

    scheduler = lambda *_: None  # noqa: E731
    with (
        patch("backend.download_pipeline.pipeline.acquire_video", side_effect=stage("acquire", acquired(video_path, TRANSCRIPT))),
        patch(
            "backend.download_pipeline.pipeline.store_video",
            side_effect=stage("store", StorageOutcome(stored_video=STORED, video_id=VIDEO_ID)),
        ),
        patch("backend.download_pipeline.pipeline.hand_over_for_visual_indexing", side_effect=hand_over),
        patch("backend.download_pipeline.pipeline.segment_and_store", side_effect=stage("segment", SegmentedVideo(memory_count=1, chapter_count=1))),
        patch("backend.download_pipeline.pipeline.embed_video", side_effect=stage("embed", EmbeddedVideo(memory_count=1, chapter_count=1))),
        patch("backend.download_pipeline.pipeline.generate_and_store_insights", side_effect=stage("insights", InsightGenerationOutcome(stored=True))),
    ):
        run_download_pipeline(
            AcquisitionRoute.COMPANION_DOWNLOAD,
            request=CreateVideoJobRequest(page_url="https://example.com/watch", page_title="Example"),
            download_root=tmp_path,
            job_id="job-42",
            acquisition_mode="companion_download",
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
            schedule_visual_indexing=scheduler,
        )

    assert order == ["acquire", "store", "visual", "segment", "embed", "insights"]


def _complete_a_browser_download(manager: JobManager, tmp_path: Path) -> Path:
    """Drive one job whose video is recorded, through the manager's real completion path."""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    request = CreateVideoJobRequest(
        page_url="https://example.com/watch",
        page_title="Example",
        media_candidates=[MediaCandidate(kind=MediaKind.DIRECT, url="https://cdn.example.com/v.mp4")],
        browser_context=BrowserContext(),
    )
    with patch("backend.services.video_download.jobs.validate_remote_url"):
        created = manager.create(request)
    with (
        patch("backend.services.video_download.jobs.validate_local_media_path", return_value=video_path),
        # The job moves the file into its workspace first, so the result names wherever it went.
        patch(
            "backend.download_pipeline.acquisition.process_downloaded_video",
            side_effect=lambda *, video, **_: acquired(video.video_path),
        ),
        patch("backend.download_pipeline.video_storage.upload_job_video", return_value=STORED),
        patch("backend.download_pipeline.video_storage.record_job_video", return_value=SimpleNamespace(id=VIDEO_ID)),
    ):
        manager.complete_browser_download(
            created.job_id, BrowserDownloadCompleteRequest(local_path=str(video_path))
        )
        manager._executor.shutdown(wait=True)
    return video_path


def test_a_recorded_video_is_indexed_on_the_visual_executor_which_owns_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    seen = {}

    def index(video_id, local_path, *, stop_event, ocr_engine):
        seen.update(
            thread=threading.current_thread().name,
            video_id=video_id,
            existed=local_path.exists(),
            ocr_engine=ocr_engine,
        )
        local_path.unlink()

    manager = JobManager(tmp_path)
    try:
        with patch(INDEX_PATH, side_effect=index):
            video_path = _complete_a_browser_download(manager, tmp_path)
            manager._visual_executor.shutdown(wait=True)
    finally:
        manager.shutdown()

    assert seen["thread"].startswith("vidseek-visual")
    assert seen["video_id"] == VIDEO_ID
    # The upload no longer deletes the file; the visual task is the one reading it.
    assert seen["existed"] is True
    assert not video_path.exists()
    # No OCR environment is configured in the suite, so the task is told to leave text unread.
    assert seen["ocr_engine"] is None


def test_with_visual_indexing_off_nothing_is_scheduled_and_the_file_goes(
    tmp_path: Path,
) -> None:
    manager = JobManager(tmp_path)
    try:
        with (
            patch(INDEX_PATH) as index,
            patch("backend.download_pipeline.visual_indexing.PostgresVisualIndex"),
        ):
            video_path = _complete_a_browser_download(manager, tmp_path)
            manager._visual_executor.shutdown(wait=True)
    finally:
        manager.shutdown()

    assert not index.called
    assert not video_path.exists()


def test_a_task_the_manager_shut_down_before_running_still_deletes_its_file(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    indexed = []

    def occupy_the_worker(video_id, local_path, *, stop_event, ocr_engine):
        indexed.append(local_path)
        started.set()
        release.wait(timeout=10)

    running = tmp_path / "running.mp4"
    queued = tmp_path / "queued.mp4"
    running.write_bytes(b"video")
    queued.write_bytes(b"video")
    manager = JobManager(tmp_path)
    with (
        patch(INDEX_PATH, side_effect=occupy_the_worker),
        patch("backend.services.video_download.jobs.mark_visual_indexing_never_run") as mark_never_run,
    ):
        manager._schedule_visual_indexing(VIDEO_ID, running)
        assert started.wait(timeout=10)
        manager._schedule_visual_indexing(VIDEO_ID, queued)
        manager.shutdown()
        release.set()
        manager._visual_executor.shutdown(wait=True)

    # Shutting down tells the running index to stop at its next frame.
    assert manager._visual_stop.is_set()
    # Both files moved into the visual queue when they were scheduled. The one never run is
    # gone from it; the one still being read is not.
    queue = tmp_path / "visual-queue"
    assert not running.exists() and not queued.exists()
    assert list(queue.iterdir()) == indexed
    assert indexed[0].exists()
    # The one never run is marked interrupted, so the next start builds its index.
    assert [call.args for call in mark_never_run.call_args_list] == [(VIDEO_ID,)]


def test_the_visual_indexing_switch_reads_true_and_false_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIDSEEK_VISUAL_INDEXING")
    assert config.visual_indexing_enabled() is True
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "off")
    assert config.visual_indexing_enabled() is False
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "sometimes")
    with pytest.raises(RuntimeError, match="VIDSEEK_VISUAL_INDEXING"):
        config.visual_indexing_enabled()


def test_the_index_version_names_the_model_the_encoder_loads() -> None:
    from backend.services.embeddings.image_embedding import MODEL_NAME
    from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION, IMAGE_MODEL_NAME

    assert IMAGE_MODEL_NAME == MODEL_NAME
    assert CURRENT_VISUAL_INDEX_VERSION == "siglip2-base-patch16-256@0.5fps"
