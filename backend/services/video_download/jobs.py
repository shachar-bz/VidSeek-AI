"""Single-worker in-memory job orchestration for the local companion API."""

from __future__ import annotations

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

from .web.downloader import DownloadedVideo
from .web.pipeline import download_and_transcribe, process_downloaded_video
from .youtube_job import run_youtube_job


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
            self._finish(job_id, result)
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
            self._finish(job_id, result)
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
            self._finish(job_id, result)
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

    def _finish(self, job_id: str, result) -> None:
        with self._lock:
            job = self._require(job_id)
            job.video_path = str(result.video_path)
            job.transcript_text_path = (
                str(result.transcript_text_path) if result.transcript_text_path else None
            )
            job.transcript_json_path = (
                str(result.transcript_json_path) if result.transcript_json_path else None
            )
            job.transcript_source = result.transcript_source
            job.comments_path = str(result.comments_path) if result.comments_path else None
            job.phase = JobPhase.COMPLETE
            job.progress = 1.0
            if result.transcript_error:
                job.status = JobStatus.PARTIAL_SUCCESS
                job.error_code = "transcription_failed"
                job.message = "Video saved; transcription can be retried"
            else:
                job.status = JobStatus.COMPLETE
                job.message = "Video and transcript saved"

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
