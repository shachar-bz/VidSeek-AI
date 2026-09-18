"""Single-worker in-memory job state for the local companion API.

What a job *does* is `backend.download_pipeline`'s: acquire the video, store it, divide it
into memories and chapters, and embed them. What is left here is everything about a job that
the pipeline has no opinion on — which of the three acquisition routes a page URL calls for,
how far along the extension is told the work is, what a cancel request does to a run already
under way, and when the browser-supplied cookies are wiped.

The one piece of real judgment still in this module is how a pipeline result becomes a
status. The pipeline reports what it could not do as problem codes and finishes anyway, and
this is where that turns into `complete`, `partial_success` or `failed` and into the sentence
the extension shows.
"""

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
from backend.download_pipeline import (
    CHAPTER_GROUPING_FAILED,
    EMBEDDING_FAILED,
    RECORD_FAILED,
    SEGMENTATION_FAILED,
    AcquisitionRoute,
    ProcessedVideo,
    VideoStorageError,
    run_download_pipeline,
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

from .web.pipeline import UNTIMED_TRANSCRIPT_ERROR

TRANSCRIPTION_FAILED = "transcription_failed"
UPLOAD_FAILED = "upload_failed"

# What a partially successful job says it kept, and what went wrong with the rest.
SAVED_BY_TRANSCRIPT_PROBLEM = {
    UNTIMED_TRANSCRIPT_ERROR: "Video and text saved",
    TRANSCRIPTION_FAILED: "Video saved",
    None: "Video and transcript saved",
}
PROBLEM_DESCRIPTIONS = {
    UNTIMED_TRANSCRIPT_ERROR: "no timing could be measured",
    TRANSCRIPTION_FAILED: "transcription can be retried",
    RECORD_FAILED: "the video is in Blob Storage but was not recorded in the database",
    SEGMENTATION_FAILED: "its moments could not be found",
    CHAPTER_GROUPING_FAILED: "its moments were found but not grouped into chapters",
    EMBEDDING_FAILED: "it is not searchable yet",
}

# Which acquisition route each of `create`'s modes runs on. The mode is the name the
# extension is given and the route is what the pipeline dispatches on; they are not one
# value because `captured_request` is a second attempt down the companion's own route
# rather than a route of its own.
ROUTE_BY_ACQUISITION_MODE = {
    "youtube_pipeline": AcquisitionRoute.YOUTUBE,
    "companion_download": AcquisitionRoute.COMPANION_DOWNLOAD,
    "captured_request": AcquisitionRoute.COMPANION_DOWNLOAD,
    "browser_download": AcquisitionRoute.DOWNLOADED_FILE,
}

# What a job says when it could not obtain the video at all, named after the attempt that
# failed rather than after the exception, which the extension has no use for.
DOWNLOAD_FAILURE_BY_ACQUISITION_MODE = {
    "youtube_pipeline": "YouTube download failed",
    "companion_download": "Authenticated download failed",
    "captured_request": "Authenticated download failed",
}


def _transcript_problem(transcript_error: str | None) -> str | None:
    """Which transcript problem a pipeline reported, in the extension's vocabulary.

    The pipeline names the one case it can describe precisely — text with no timing on it
    — and reports every other failure as the exception that caused it, which is the
    companion's business rather than the tab's.
    """
    if transcript_error == UNTIMED_TRANSCRIPT_ERROR:
        return UNTIMED_TRANSCRIPT_ERROR
    return TRANSCRIPTION_FAILED if transcript_error else None


def _partial_success_message(transcript_problem: str | None, later_problems: list[str]) -> str:
    """What a job that produced something, but not everything, tells the extension.

    The transcript problem leads, because it decides what the job can claim to have saved
    at all; everything after it describes a video that is already stored. The later problems
    are listed in the order the stages hit them, so the first named is the earliest thing
    that went wrong and therefore the one most likely to explain the rest.
    """
    described = " and ".join(
        PROBLEM_DESCRIPTIONS[problem]
        for problem in ([transcript_problem] if transcript_problem else []) + later_problems
    )
    return f"{SAVED_BY_TRANSCRIPT_PROBLEM[transcript_problem]}; {described}"


@dataclass
class _Job:
    job_id: str
    request: CreateVideoJobRequest
    status: JobStatus
    phase: JobPhase
    acquisition_mode: str
    # The account that started this job, or None for a request nothing required a
    # signed-in account for; handed to the pipeline, which puts it on the video row.
    user_id: str | None = None
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

    def create(
        self, request: CreateVideoJobRequest, user_id: str | None = None
    ) -> VideoJobResponse:
        """Validate the request and start it on the pipeline its page URL calls for.

        The choice of pipeline is made here rather than by the extension, because the
        companion cannot take a client's word for which route to run and would have to
        classify the URL anyway. A second endpoint would only duplicate that authority.

        `user_id` names the account the video row this job eventually writes will belong
        to. It is optional here, not because an anonymous job is desired, but because
        requiring it is the API route's job (`current_user_for_job_creation`): this
        manager only carries whatever the caller already resolved.
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
            user_id=user_id,
            message=message,
        )
        with self._lock:
            self._jobs[job_id] = job
        if is_youtube:
            self._executor.submit(self._run, job_id, can_capture_on_failure=False)
        elif not direct_only:
            self._executor.submit(self._run, job_id, can_capture_on_failure=True)
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
        self._executor.submit(
            self._run, job_id, can_capture_on_failure=False, local_path=path
        )
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
        self._executor.submit(self._run, job_id, can_capture_on_failure=True)
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

    def _run(
        self, job_id: str, *, can_capture_on_failure: bool, local_path: Path | None = None
    ) -> None:
        """Run one job's pipeline and record what it produced, or why it produced nothing.

        One body for all three routes, because the pipeline is the same for all three once
        the route is chosen. What still differs is only how a failure is reported: a
        download the companion attempted itself can be retried with a request captured from
        the browser, while a YouTube download cannot -- capturing a googlevideo request
        would not help, since that route never used the browser's request in the first place
        -- and neither can a file Chrome already downloaded, whose video is on disk and
        whose failure was therefore in processing it.
        """
        with self._lock:
            job = self._require(job_id)
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.RUNNING
            request, acquisition_mode, user_id = job.request, job.acquisition_mode, job.user_id
        try:
            processed = run_download_pipeline(
                ROUTE_BY_ACQUISITION_MODE[acquisition_mode],
                request=request,
                download_root=self.download_root,
                job_id=job_id,
                acquisition_mode=acquisition_mode,
                cancel_event=job.cancel_event,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
                user_id=user_id,
                local_path=local_path,
            )
        except DownloadCancelled:
            self._mark_cancelled(job_id)
        except VideoStorageError as error:
            self._fail(
                job_id,
                UPLOAD_FAILED,
                f"Storing the video in Blob Storage failed ({type(error.__cause__).__name__})",
                can_capture=False,
            )
        except UnsupportedMediaError as error:
            self._fail(job_id, "unsupported_media", str(error), can_capture=False)
        except Exception as error:
            self._fail_acquisition(
                job_id,
                error,
                acquisition_mode=acquisition_mode,
                can_capture=can_capture_on_failure,
                local_path=local_path,
            )
        else:
            self._finish(job_id, processed)

    def _fail_acquisition(
        self,
        job_id: str,
        error: Exception,
        *,
        acquisition_mode: str,
        can_capture: bool,
        local_path: Path | None,
    ) -> None:
        """Report a run that never got as far as a stored video, in the route's own terms.

        A file Chrome already downloaded is the one route whose failure here is partial
        rather than total: the video is on disk and stays there, so the job keeps it and
        says the transcript processing is what went wrong.
        """
        if local_path is not None:
            with self._lock:
                self._require(job_id).video_path = str(local_path)
            self._fail(
                job_id,
                "transcript_failed",
                f"Video retained; transcript processing failed ({type(error).__name__})",
                can_capture=False,
                partial=True,
            )
            return
        attempt = DOWNLOAD_FAILURE_BY_ACQUISITION_MODE.get(
            acquisition_mode, "Download failed"
        )
        self._fail(
            job_id,
            "download_failed",
            f"{attempt} ({type(error).__name__})",
            can_capture=can_capture,
        )

    def _finish(self, job_id: str, processed: ProcessedVideo) -> None:
        """Publish a finished run's result, as complete or as complete-with-caveats.

        Everything the pipeline reports as a problem describes a video that is already in
        Blob Storage: text with no timing on it, a row that was not written, moments that
        were not found, vectors that were not built. None of those is worth failing a job
        that produced a stored video, so all of them come back as `partial_success` with the
        earliest problem as the code -- while a run that never stored the video at all
        raised long before reaching here.
        """
        acquired = processed.acquired
        with self._lock:
            job = self._require(job_id)
            # The video now lives only in Blob Storage; the local copy made for
            # transcription is gone.
            job.video_path = None
            job.transcript_text_path = (
                str(acquired.transcript_text_path) if acquired.transcript_text_path else None
            )
            job.transcript_json_path = (
                str(acquired.transcript_json_path) if acquired.transcript_json_path else None
            )
            job.transcript_source = acquired.transcript_source
            job.comments_path = str(acquired.comments_path) if acquired.comments_path else None
            job.video_storage_key = processed.stored_video.name
            job.phase = JobPhase.COMPLETE
            job.progress = 1.0
            transcript_problem = _transcript_problem(acquired.transcript_error)
            later_problems = list(processed.problems)
            if transcript_problem or later_problems:
                job.status = JobStatus.PARTIAL_SUCCESS
                job.error_code = transcript_problem or later_problems[0]
                job.message = _partial_success_message(transcript_problem, later_problems)
            else:
                job.status = JobStatus.COMPLETE
                job.message = (
                    f"Video uploaded; transcript saved; {processed.memory_count} moments "
                    f"in {processed.chapter_count} chapters indexed"
                    if processed.is_searchable
                    else "Video uploaded; transcript saved"
                )
            self._discard_secrets(job_id)

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
            self._discard_secrets(job_id)

    def _mark_cancelled(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled"
            job.can_capture = False
            self._discard_secrets(job_id)

    def _discard_secrets(self, job_id: str) -> None:
        """Clear this job's browser-supplied secrets.

        Always called from inside the same lock acquisition that publishes the job's
        terminal status (`_fail`, `_mark_cancelled`, `_finish`, and `cancel`'s own inline
        transition to CANCELLED) rather than afterwards. Otherwise a `retry_with_capture`
        call landing between the status write and this cleanup would install fresh
        captured cookies/headers just in time for this call to wipe them instead of the
        stale ones it was meant to discard. `self._lock` is reentrant, so nesting here is
        safe.
        """
        with self._lock:
            job = self._require(job_id)
            job.request.browser_context.cookies.clear()
            job.request.browser_context.headers.clear()
            for candidate in job.request.media_candidates:
                candidate.headers.clear()
            if not job.can_capture:
                for caption in job.request.caption_candidates:
                    caption.text = None
