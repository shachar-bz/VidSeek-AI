"""Single-worker in-memory job orchestration for the local companion API."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from yt_dlp.utils import DownloadCancelled

from backend.core.errors import (
    JobNotFoundError,
    JobStateConflictError,
    UnsupportedMediaError,
)
from backend.core.security import (
    is_youtube_url,
    validate_local_media_path,
    validate_remote_url,
)
from backend.schemas.browser import MediaKind
from backend.schemas.video_jobs import (
    BrowserDownloadCompleteRequest,
    CaptureRetryRequest,
    CreateVideoJobRequest,
    JobPhase,
    JobStatus,
    VideoJobResponse,
)
from backend.storage.r2 import StoredVideo

from .video_record import record_job_video
from .video_upload import upload_job_video
from .web.downloader import DownloadedVideo
from .web.pipeline import (
    UNTIMED_TRANSCRIPT_ERROR,
    download_and_transcribe,
    process_downloaded_video,
)
from .youtube_job import run_youtube_job

TRANSCRIPTION_FAILED = "transcription_failed"
UPLOAD_FAILED = "upload_failed"
RECORD_FAILED = "record_failed"

# What a partially successful job says it kept, and what went wrong with the rest.
SAVED_BY_TRANSCRIPT_PROBLEM = {
    UNTIMED_TRANSCRIPT_ERROR: "Video and text saved",
    TRANSCRIPTION_FAILED: "Video saved",
    None: "Video and transcript saved",
}
PROBLEM_DESCRIPTIONS = {
    UNTIMED_TRANSCRIPT_ERROR: "no timing could be measured",
    TRANSCRIPTION_FAILED: "transcription can be retried",
    RECORD_FAILED: "the video is in R2 but was not recorded in Supabase",
}

logger = logging.getLogger(__name__)


def _transcript_problem(transcript_error: str | None) -> str | None:
    """Which transcript problem a pipeline reported, in the extension's vocabulary.

    The pipeline names the one case it can describe precisely — text with no timing on it
    — and reports every other failure as the exception that caused it, which is the
    companion's business rather than the tab's.
    """
    if transcript_error == UNTIMED_TRANSCRIPT_ERROR:
        return UNTIMED_TRANSCRIPT_ERROR
    return TRANSCRIPTION_FAILED if transcript_error else None


def _partial_success_message(transcript_problem: str | None, record_problem: str | None) -> str:
    """What a job that produced something, but not everything, tells the extension.

    At most two problems can arrive here. The transcript's half and the Supabase half fail
    independently, but the Supabase half fails in only one way per job: recording a video
    is attempted only once its upload has already returned an object key.
    """
    problems = [problem for problem in (transcript_problem, record_problem) if problem]
    described = " and ".join(PROBLEM_DESCRIPTIONS[problem] for problem in problems)
    return f"{SAVED_BY_TRANSCRIPT_PROBLEM[transcript_problem]}; {described}"


@dataclass
class _Job:
    job_id: str
    request: CreateVideoJobRequest
    status: JobStatus
    phase: JobPhase
    acquisition_mode: str
    progress: float = 0.0
    message: str = "Waiting"
    video_path: str | None = None
    transcript_text_path: str | None = None
    transcript_json_path: str | None = None
    transcript_source: str | None = None
    comments_path: str | None = None
    video_storage_key: str | None = None
    error_code: str | None = None
    can_capture: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def public(self) -> VideoJobResponse:
        return VideoJobResponse(
            job_id=self.job_id,
            status=self.status,
            phase=self.phase,
            progress=self.progress,
            message=self.message,
            acquisition_mode=self.acquisition_mode,
            video_path=self.video_path,
            transcript_text_path=self.transcript_text_path,
            transcript_json_path=self.transcript_json_path,
            transcript_source=self.transcript_source,
            comments_path=self.comments_path,
            video_storage_key=self.video_storage_key,
            error_code=self.error_code,
            can_capture=self.can_capture,
        )


class JobManager:
    """Runs one resource-heavy download/transcription job at a time."""

    def __init__(self, download_root: Path):
        self.download_root = download_root
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vidseek-job")

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def create(self, request: CreateVideoJobRequest) -> VideoJobResponse:
        """Validate the request and start it on the pipeline its page URL calls for.

        The choice of pipeline is made here rather than by the extension, because the
        companion cannot take a client's word for which route to run and would have to
        classify the URL anyway. A second endpoint would only duplicate that authority.
        """
        validate_remote_url(request.page_url)
        for candidate in request.media_candidates:
            validate_remote_url(candidate.url)
        if request.drm_detected:
            raise UnsupportedMediaError("DRM-protected media is not supported")

        is_youtube = is_youtube_url(request.page_url)
        # A YouTube page's own media URLs are googlevideo links that expire and refuse
        # a second reader, so the YouTube pipeline always fetches for itself.
        direct_only = (
            not is_youtube
            and bool(request.media_candidates)
            and all(candidate.kind == MediaKind.DIRECT for candidate in request.media_candidates)
        )
        if is_youtube:
            acquisition_mode = "youtube_pipeline"
            message = "Queued for YouTube download"
        elif direct_only:
            acquisition_mode = "browser_download"
            message = "Waiting for Chrome to download the direct media file"
        else:
            acquisition_mode = "companion_download"
            message = "Queued for authenticated download"

        job_id = uuid.uuid4().hex
        job = _Job(
            job_id=job_id,
            request=request,
            status=(
                JobStatus.AWAITING_BROWSER_DOWNLOAD if direct_only else JobStatus.QUEUED
            ),
            phase=JobPhase.DOWNLOAD,
            acquisition_mode=acquisition_mode,
            message=message,
        )
        with self._lock:
            self._jobs[job_id] = job
        if is_youtube:
            self._executor.submit(self._run_youtube, job_id)
        elif not direct_only:
            self._executor.submit(self._run_download, job_id)
        return job.public()

    def get(self, job_id: str) -> VideoJobResponse:
        with self._lock:
            return self._require(job_id).public()

    def complete_browser_download(
        self, job_id: str, payload: BrowserDownloadCompleteRequest
    ) -> VideoJobResponse:
        with self._lock:
            if self._require(job_id).status != JobStatus.AWAITING_BROWSER_DOWNLOAD:
                raise JobStateConflictError("Job is not waiting for a Chrome download")
        path = validate_local_media_path(payload.local_path, self.download_root)
        with self._lock:
            job = self._require(job_id)
            if job.status != JobStatus.AWAITING_BROWSER_DOWNLOAD:
                raise JobStateConflictError("Job is not waiting for a Chrome download")
            job.status = JobStatus.QUEUED
            job.message = "Chrome download complete; queued for transcript processing"
        self._executor.submit(self._run_existing_file, job_id, path)
        return self.get(job_id)

    def retry_with_capture(self, job_id: str, payload: CaptureRetryRequest) -> VideoJobResponse:
        for candidate in payload.media_candidates:
            validate_remote_url(candidate.url)
        with self._lock:
            job = self._require(job_id)
            if job.status not in {JobStatus.FAILED, JobStatus.AWAITING_BROWSER_DOWNLOAD}:
                raise JobStateConflictError("Job is not eligible for captured-request retry")
            job.request.media_candidates = payload.media_candidates
            job.request.browser_context = payload.browser_context
            job.status = JobStatus.QUEUED
            job.phase = JobPhase.DOWNLOAD
            job.progress = 0.0
            job.message = "Queued with captured browser request"
            job.error_code = None
            job.can_capture = False
            job.acquisition_mode = "captured_request"
            job.cancel_event.clear()
        self._executor.submit(self._run_download, job_id)
        return self.get(job_id)

    def cancel(self, job_id: str) -> VideoJobResponse:
        with self._lock:
            job = self._require(job_id)
            if job.status in {
                JobStatus.COMPLETE,
                JobStatus.PARTIAL_SUCCESS,
                JobStatus.CANCELLED,
            }:
                return job.public()
            job.cancel_event.set()
            if job.status != JobStatus.RUNNING:
                job.status = JobStatus.CANCELLED
                job.message = "Cancelled"
                job.can_capture = False
            response = job.public()
            if job.status == JobStatus.CANCELLED:
                self._discard_secrets(job_id)
            return response

    def _require(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise JobNotFoundError("Video job was not found") from error

    def _progress(self, job_id: str, phase: JobPhase, value: float, message: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.phase = phase
            job.progress = min(max(value, 0.0), 1.0)
            job.message = message

    def _run_youtube(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.RUNNING
            request = job.request
        try:
            result = run_youtube_job(
                request=request,
                download_root=self.download_root,
                cancel_event=job.cancel_event,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
            )
            self._store_and_finish(job_id, result)
        except DownloadCancelled:
            self._mark_cancelled(job_id)
        except Exception as error:
            # No capture retry is offered: capturing a googlevideo request would not help,
            # since the YouTube pipeline never used the browser's request in the first place.
            self._fail(
                job_id,
                "download_failed",
                f"YouTube download failed ({type(error).__name__})",
                can_capture=False,
            )
        finally:
            self._discard_secrets(job_id)

    def _run_download(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.RUNNING
            request = job.request
        try:
            result = download_and_transcribe(
                request=request,
                download_root=self.download_root,
                cancel_event=job.cancel_event,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
            )
            self._store_and_finish(job_id, result)
        except DownloadCancelled:
            self._mark_cancelled(job_id)
        except UnsupportedMediaError as error:
            self._fail(job_id, "unsupported_media", str(error), can_capture=False)
        except Exception as error:
            self._fail(
                job_id,
                "download_failed",
                f"Authenticated download failed ({type(error).__name__})",
                can_capture=True,
            )
        finally:
            self._discard_secrets(job_id)

    def _run_existing_file(self, job_id: str, path: Path) -> None:
        with self._lock:
            job = self._require(job_id)
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.RUNNING
            request = job.request
        try:
            result = process_downloaded_video(
                video=DownloadedVideo(title=request.page_title, video_path=path),
                request=request,
                cancel_event=job.cancel_event,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
            )
            self._store_and_finish(job_id, result)
        except DownloadCancelled:
            self._mark_cancelled(job_id)
        except Exception as error:
            with self._lock:
                job.video_path = str(path)
            self._fail(
                job_id,
                "transcript_failed",
                f"Video retained; transcript processing failed ({type(error).__name__})",
                can_capture=False,
                partial=True,
            )
        finally:
            self._discard_secrets(job_id)

    def _store_and_finish(self, job_id: str, result) -> None:
        """Store the video in R2, describe it in Supabase, then finish the job.

        Storage is not optional: R2 is the video's only home, so a failure here fails the
        job rather than falling back to the local copy the pipeline made to transcribe it.
        Recording the video in Supabase is not that kind of failure — the video and its
        transcript files are already durable once the upload succeeds — so a database that
        refuses the write is reported on the finished job rather than thrown away with it.
        """
        with self._lock:
            if self._require(job_id).cancel_event.is_set():
                raise DownloadCancelled("Job cancelled")
        try:
            stored_video = upload_job_video(
                video_path=result.video_path,
                job_id=job_id,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
            )
        except Exception as error:
            logger.exception("Storing %s in R2 failed", result.video_path)
            self._fail(
                job_id,
                UPLOAD_FAILED,
                f"Storing the video in R2 failed ({type(error).__name__})",
                can_capture=False,
            )
            return
        record_problem = self._record_video(job_id, result, stored_video)
        self._finish(job_id, result, stored_video=stored_video, record_problem=record_problem)

    def _record_video(self, job_id: str, result, stored_video: StoredVideo) -> str | None:
        """Describe the uploaded video in Supabase, reporting a failure rather than raising.

        The row can be written again later from the object key alone, so a database that
        is unreachable is worth reporting but not worth discarding a finished download
        over. Nothing here is retried: the upload has already happened, and a second
        attempt against a project that just refused one is unlikely to be answered
        differently within the life of the job.
        """
        with self._lock:
            job = self._require(job_id)
            request, acquisition_mode = job.request, job.acquisition_mode
        try:
            record_job_video(
                stored_video=stored_video,
                request=request,
                job_id=job_id,
                acquisition_mode=acquisition_mode,
                transcript_source=result.transcript_source,
                transcript=result.normalized_transcript,
            )
        except Exception:
            logger.exception("Recording %s in Supabase failed", stored_video.key)
            return RECORD_FAILED
        return None

    def _finish(
        self,
        job_id: str,
        result,
        *,
        stored_video: StoredVideo,
        record_problem: str | None = None,
    ) -> None:
        with self._lock:
            job = self._require(job_id)
            # The video now lives only in R2; the local copy made for transcription is gone.
            job.video_path = None
            job.transcript_text_path = (
                str(result.transcript_text_path) if result.transcript_text_path else None
            )
            job.transcript_json_path = (
                str(result.transcript_json_path) if result.transcript_json_path else None
            )
            job.transcript_source = result.transcript_source
            job.comments_path = str(result.comments_path) if result.comments_path else None
            job.video_storage_key = stored_video.key
            job.phase = JobPhase.COMPLETE
            job.progress = 1.0
            transcript_problem = _transcript_problem(result.transcript_error)
            if transcript_problem or record_problem:
                # A transcript with no timing is still text, and a video not yet described
                # in Supabase is still safely in R2 -- neither costs the job its result, so
                # both are reported rather than failing a job that otherwise finished.
                job.status = JobStatus.PARTIAL_SUCCESS
                job.error_code = transcript_problem or record_problem
                job.message = _partial_success_message(transcript_problem, record_problem)
            else:
                job.status = JobStatus.COMPLETE
                job.message = "Video uploaded; transcript saved"

    def _fail(
        self,
        job_id: str,
        code: str,
        message: str,
        *,
        can_capture: bool,
        partial: bool = False,
    ) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = JobStatus.PARTIAL_SUCCESS if partial else JobStatus.FAILED
            job.error_code = code
            job.message = message
            job.can_capture = can_capture
            if partial:
                job.phase = JobPhase.COMPLETE
                job.progress = 1.0

    def _mark_cancelled(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled"
            job.can_capture = False

    def _discard_secrets(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.request.browser_context.cookies.clear()
            job.request.browser_context.headers.clear()
            for candidate in job.request.media_candidates:
                candidate.headers.clear()
            if not job.can_capture:
                for caption in job.request.caption_candidates:
                    caption.text = None
