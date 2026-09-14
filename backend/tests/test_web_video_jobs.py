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
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    TranscriptSegment,
)
from backend.services.video_download.jobs import JobManager
from backend.services.video_download.web.pipeline import (
    UNTIMED_TRANSCRIPT_ERROR,
    PipelineResult,
)
from backend.storage.r2 import StoredVideo

STORED = StoredVideo(
    bucket="vidseek-videos",
    key="videos/job-42/video.mp4",
    size_bytes=5,
    content_type="video/mp4",
)

TRANSCRIPT = NormalizedTranscript(
    source="captions",
    timing_fidelity=TimingFidelity.CAPTION,
    segments=[TranscriptSegment(index=0, start_seconds=0.0, end_seconds=1.0, text="hello")],
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


def run_to_completion(
    manager: JobManager,
    download_root: Path,
    *,
    transcript_error: str | None = None,
    transcript: NormalizedTranscript | None = None,
    record: dict | None = None,
    **upload,
):
    """Drive one job from a Chrome download through to its recorded result.

    The file Chrome "downloaded" is the shortest way into the pipeline that still goes
    through the job manager's own completion path, which is what the upload and the
    Supabase row both hang off. `upload` and `record` are the mock keywords — `return_value`
    or `side_effect` — applied to each of those two steps.
    """
    video_path = download_root / "video.mp4"
    video_path.write_bytes(b"video")
    result = PipelineResult(
        video_path=video_path,
        transcript_text_path=None,
        transcript_json_path=None,
        transcript_source="page_transcript",
        transcript_error=transcript_error,
        normalized_transcript=transcript,
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
        patch(
            "backend.services.video_download.jobs.record_job_video",
            **(record or {"return_value": None}),
        ),
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
    # The video lives only in R2 once the job is done; the local copy is gone.
    assert job.video_path is None


def test_an_unreachable_bucket_fails_the_job_rather_than_keeping_a_local_copy(
    tmp_path: Path,
) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(manager, tmp_path, side_effect=OSError("bucket unreachable"))
    finally:
        manager.shutdown()

    # R2 is the video's only home, so a storage failure fails the job instead of quietly
    # settling for the local copy the pipeline made to transcribe it.
    assert job.status == JobStatus.FAILED
    assert job.error_code == "upload_failed"
    assert job.video_storage_key is None


def test_an_untimed_transcript_still_says_so_when_the_upload_worked(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(
            manager, tmp_path, transcript_error=UNTIMED_TRANSCRIPT_ERROR, return_value=STORED
        )
    finally:
        manager.shutdown()

    assert job.status == JobStatus.PARTIAL_SUCCESS
    assert job.error_code == UNTIMED_TRANSCRIPT_ERROR
    assert job.message == "Video and text saved; no timing could be measured"
    assert job.video_storage_key == STORED.key


def test_an_untimed_transcript_does_not_mask_a_storage_failure(tmp_path: Path) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(
            manager,
            tmp_path,
            transcript_error=UNTIMED_TRANSCRIPT_ERROR,
            side_effect=OSError("bucket unreachable"),
        )
    finally:
        manager.shutdown()

    # A transcript-only problem is reported as saved-with-a-caveat; a storage failure is
    # not -- nothing is durably saved when the video never made it into the bucket.
    assert job.status == JobStatus.FAILED
    assert job.error_code == "upload_failed"


def capture_records() -> tuple[list[dict], dict]:
    """A `record` argument for `run_to_completion` that keeps what it was called with."""
    written: list[dict] = []
    return written, {"side_effect": lambda **kwargs: written.append(kwargs)}


def test_an_uploaded_video_is_described_in_supabase_before_the_job_reports_done(
    tmp_path: Path,
) -> None:
    written, record = capture_records()
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(manager, tmp_path, return_value=STORED, record=record)
    finally:
        manager.shutdown()

    assert job.status == JobStatus.COMPLETE
    assert written[0]["stored_video"] == STORED
    assert written[0]["acquisition_mode"] == "browser_download"
    assert written[0]["transcript_source"] == "page_transcript"
    assert written[0]["job_id"] == job.job_id


def test_the_transcript_reaches_supabase_from_the_pipeline_not_from_the_json_on_disk(
    tmp_path: Path,
) -> None:
    # Re-reading the file the pipeline just wrote would be a second chance to read it
    # differently, and the segments are already in hand.
    written, record = capture_records()
    manager = JobManager(tmp_path)
    try:
        run_to_completion(
            manager, tmp_path, return_value=STORED, record=record, transcript=TRANSCRIPT
        )
    finally:
        manager.shutdown()

    assert written[0]["transcript"] is TRANSCRIPT


def test_a_video_that_never_reached_the_bucket_is_not_described_as_if_it_had(
    tmp_path: Path,
) -> None:
    # r2_object_key is the whole point of the row, and a failed upload produced none.
    written, record = capture_records()
    manager = JobManager(tmp_path)
    try:
        run_to_completion(
            manager, tmp_path, side_effect=OSError("bucket unreachable"), record=record
        )
    finally:
        manager.shutdown()

    assert written == []


def test_an_unreachable_database_leaves_the_uploaded_video_flagged_as_unrecorded(
    tmp_path: Path,
) -> None:
    manager = JobManager(tmp_path)
    try:
        job = run_to_completion(
            manager,
            tmp_path,
            return_value=STORED,
            record={"side_effect": OSError("supabase unreachable")},
        )
    finally:
        manager.shutdown()

    # The video is in R2 and on disk, so the job keeps its result; what it lost is the
    # row that would let anything find the object again.
    assert job.status == JobStatus.PARTIAL_SUCCESS
    assert job.error_code == "record_failed"
    assert job.video_storage_key == STORED.key
    assert job.message == (
        "Video and transcript saved; the video is in R2 but was not recorded in Supabase"
    )
