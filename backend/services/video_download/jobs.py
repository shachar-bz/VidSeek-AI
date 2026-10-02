"""Single-worker job state for the local companion API, in memory while a job runs.

What a job *does* is `backend.download_pipeline`'s: acquire the video, store it, divide it
into memories and chapters, embed them, and generate insights. What is left here is everything
about a job that the pipeline has no opinion on — which of the three acquisition routes a page
URL calls for, how far along the extension is told the work is, what a cancel request does to a
run already under way, and when the browser-supplied cookies are wiped.

The one piece of real judgment still in this module is how a pipeline result becomes a
status. The pipeline reports what it could not do as problem codes and finishes anyway, and
this is where that turns into `complete`, `partial_success` or `failed` and into the sentence
the extension shows.

With a database configured, this module is no longer the only place a job's status lives.
Every externally meaningful change -- status, phase, progress, message, error code,
video_id -- is mirrored to `video_jobs` as it happens, and a job that reaches a status
nothing can still act on (complete, partial success, or an outright cancel; not a failure,
which `retry_with_capture` can still act on) is dropped from the in-memory dictionary once
that mirror write lands, so this process only ever holds what an active run needs: secrets
and cancellation state. A page whose video is already recorded skips the pipeline
altogether -- `create` checks `videos.normalized_source_url` first and reports a completed
job without ever entering this dictionary.

Two executors, one worker each. The job executor runs the pipeline -- download, store, then
the transcript stages -- and a job's slot frees when those finish. The visual executor runs
the visual indexing the pipeline hands over right after Store, so the next job's transcript
stages may overlap this video's indexing, while two indexing runs never share the GPU. A job
reports done without waiting for its index; `videos.visual_status` tracks that separately.

Every file a run writes lives in a folder of its own, `jobs/<job_id>` under the download root:
the video, a download's `.part` fragments, subtitles, transcripts, comments and the thumbnail,
and a file Chrome downloaded, which is moved in when the run starts. The folder is deleted
when the run ends, however it ends, so no route or failure has to know which files it made.
The one file that outlives a run is the video handed to visual indexing, which moves to
`visual-queue` first and is deleted by the visual task. Nothing in either folder survives a
restart that anything could use -- jobs and the visual queue are both in memory -- so a new
manager empties both, which clears up after a process that crashed or was killed. What does
survive is each video's `visual_status`: an index a shutdown stopped, or never got to, is
marked interrupted, one a killed process left behind is abandoned once it has long gone
unchanged, and `resume_interrupted_visual_indexing` builds either again from the copy in Blob
Storage once the app has started.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp.utils import DownloadCancelled

from backend.core import config
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
    INSIGHT_GENERATION_FAILED,
    RECORD_FAILED,
    SEGMENTATION_FAILED,
    AcquisitionRoute,
    ProcessedVideo,
    VideoStorageError,
    claim_interrupted_visual_indexing,
    index_video_visually,
    mark_visual_indexing_never_run,
    reindex_video_visually,
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
from backend.services.ocr import configured_ocr_engine
from backend.storage.postgres import (
    PostgresUserVideos,
    PostgresVideoJobs,
    PostgresVideoRecords,
    StoredVideoRecord,
    VideoJob,
    is_postgres_configured,
)

from .web.pipeline import UNTIMED_TRANSCRIPT_ERROR

logger = logging.getLogger(__name__)

TRANSCRIPTION_FAILED = "transcription_failed"
UPLOAD_FAILED = "upload_failed"
PROCESSING_FAILED = "processing_failed"

# The download root's two folders this module owns, and empties when it starts. Nothing else
# under the root is touched: Chrome saves into the root itself, and the transcript store
# keeps its own folder beside these.
JOB_WORKSPACES_DIRECTORY_NAME = "jobs"
VISUAL_INDEXING_QUEUE_DIRECTORY_NAME = "visual-queue"

# The acquisition mode a deduplicated job reports: it never chose one of the three real
# routes, because it never downloaded anything.
DEDUPLICATED_ACQUISITION_MODE = "deduplicated"

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
    INSIGHT_GENERATION_FAILED: "its generated insights are not available yet",
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
    # The `videos` row this job produced, once stage two of the pipeline has run. Mirrored
    # to `video_jobs.video_id` so anything sharing the database can follow a job to its
    # video before this process has any other reason to keep the job in memory.
    video_id: str | None = None
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
            video_id=self.video_id,
            error_code=self.error_code,
            can_capture=self.can_capture,
        )


def _response_from_persisted_job(job: VideoJob) -> VideoJobResponse:
    """Rebuild a job's response from `video_jobs` alone, for a job this process no longer holds.

    Only what that table mirrors survives an eviction or a restart -- status, phase,
    progress, message, error code and video_id -- so the fields describing an in-progress
    run's local artifacts (paths, capture eligibility) come back at their defaults. A
    finished job already reports those the same way: `_finish` clears `video_path` the
    moment the video is durably stored, and `video_storage_key`, looked up from the video
    row, is the one artifact field a caller still needs once a job is done.
    """
    return VideoJobResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        phase=JobPhase(job.phase),
        progress=job.progress,
        message=job.message,
        acquisition_mode=job.acquisition_mode or "",
        error_code=job.error_code,
        video_storage_key=_blob_name_for_video(job.video_id),
        video_id=job.video_id,
    )


def _delete_local_path(path: Path) -> None:
    """Delete a file or a whole folder, logging rather than raising if it will not go.

    A file another process still has open -- an ffmpeg a cancel did not wait for, on Windows
    -- is the usual reason; the next manager to start clears whatever this one left.
    """
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Deleting the local copy %s failed", path)


def _empty_directory(directory: Path) -> None:
    """Create `directory` if it is missing, and delete everything already inside it."""
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        _delete_local_path(child)


def _mark_if_never_run(video_id: str, finished: Future) -> None:
    """Mark a visual task the manager shut down before it started as interrupted."""
    if finished.cancelled():
        mark_visual_indexing_never_run(video_id)


def _blob_name_for_video(video_id: str | None) -> str | None:
    """The blob name a job's recorded video lives under, or None.

    Called only once a database is already known to be configured -- there is no `video_id`
    to look up otherwise, since nothing here was ever recorded without one.
    """
    if video_id is None:
        return None
    record = PostgresVideoRecords().get_by_id(video_id)
    return record.video.blob_name if record else None


class JobManager:
    """Runs one resource-heavy download/transcription job at a time."""

    def __init__(self, download_root: Path):
        self.download_root = download_root
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._job_workspaces = download_root / JOB_WORKSPACES_DIRECTORY_NAME
        self._visual_indexing_queue = download_root / VISUAL_INDEXING_QUEUE_DIRECTORY_NAME
        # Whatever is in these was left by an earlier process, whose jobs and visual queue
        # died with it.
        _empty_directory(self._job_workspaces)
        _empty_directory(self._visual_indexing_queue)
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vidseek-job")
        self._visual_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vidseek-visual"
        )
        # Set on shutdown, so an index being built stops at its next frame instead of
        # holding the process open for the rest of a long video.
        self._visual_stop = threading.Event()

    def shutdown(self) -> None:
        self._visual_stop.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._visual_executor.shutdown(wait=False, cancel_futures=True)

    def resume_interrupted_visual_indexing(self) -> None:
        """Index again every video whose visual index an earlier process interrupted or abandoned.

        Called once when the app starts. The claim runs on the visual executor rather than
        here, so a slow database cannot hold up startup; each claimed video then queues behind
        it as a task of its own, which fetches the stored video back from Blob Storage, since
        the local copy went with the process that was interrupted.
        """
        if not config.visual_indexing_enabled() or not is_postgres_configured():
            return
        self._visual_executor.submit(self._queue_interrupted_visual_indexing)

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

        Before any of that, the page is checked against what is already recorded
        (`videos.normalized_source_url`): a hit means this exact video has already been
        downloaded, transcribed, segmented and embedded by some earlier job, and the only
        thing left to do is link it into this account's library and say so.
        """
        validate_remote_url(request.page_url)
        for candidate in request.media_candidates:
            validate_remote_url(candidate.url)
        if request.drm_detected:
            raise UnsupportedMediaError("DRM-protected media is not supported")

        if is_postgres_configured():
            existing = PostgresVideoRecords().find_by_normalized_source_url(request.source_identity_url)
            if existing is not None:
                return self._create_deduplicated_job(request, existing, user_id=user_id)

        is_youtube = is_youtube_url(request.page_url)
        # A YouTube page's own media URLs are googlevideo links that expire and refuse
        # a second reader, so the YouTube pipeline always fetches for itself.
        direct_only = (
            not is_youtube
            and not request.structured_candidates
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
            self._persist(job)
        if is_youtube:
            self._executor.submit(self._run, job_id, can_capture_on_failure=False)
        elif not direct_only:
            self._executor.submit(self._run, job_id, can_capture_on_failure=True)
        return job.public()

    def _create_deduplicated_job(
        self, request: CreateVideoJobRequest, existing: StoredVideoRecord, *, user_id: str | None
    ) -> VideoJobResponse:
        """Report a job that is already done, because its video already is.

        No `_Job` is ever created for this: there is no download to cancel, no browser
        secrets to hold, and nothing an in-memory runtime dictionary is for. The job row
        goes straight to `video_jobs`, complete from the moment anything else can see it.
        """
        if user_id is not None:
            PostgresUserVideos().link(user_id, existing.id)
        message = "Video already in the library; nothing to download"
        stored = PostgresVideoJobs().upsert(
            VideoJob(
                id=uuid.uuid4().hex,
                page_url=request.page_url,
                page_title=request.page_title,
                status=JobStatus.COMPLETE.value,
                phase=JobPhase.COMPLETE.value,
                progress=1.0,
                message=message,
                user_id=user_id,
                video_id=existing.id,
                acquisition_mode=DEDUPLICATED_ACQUISITION_MODE,
            )
        )
        return _response_from_persisted_job(stored.job)

    def get(self, job_id: str) -> VideoJobResponse:
        """This job's current status, from memory while it runs and from the database after.

        With a database configured, a job falls out of `self._jobs` once it reaches a
        status nothing can still act on (`_finish`, `_mark_cancelled`, an outright cancel), and a deduplicated job is never in it at all
        -- so a caller asking about either has to be answered from `video_jobs` instead.
        Without one, eviction never happens and this dictionary answers everything, exactly
        as it always has.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job.public()
        stored = PostgresVideoJobs().get_by_id(job_id) if is_postgres_configured() else None
        if stored is None:
            raise JobNotFoundError("Video job was not found")
        return _response_from_persisted_job(stored.job)

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
            self._persist(job)
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
            selected = job.request.media_candidates
            candidates = payload.media_candidates
            if job.request.selected_media_id:
                # A retry may observe sibling videos and ads. Only refresh URLs for the
                # same resource path; if playback changed, require a fresh inspection.
                paths = {(urlsplit(c.url).netloc, urlsplit(c.url).path) for c in selected}
                candidates = [c for c in candidates if (urlsplit(c.url).netloc, urlsplit(c.url).path) in paths]
                if not candidates:
                    raise JobStateConflictError("Capture did not match the selected video; inspect it again")
            elif len(candidates) > 1:
                raise JobStateConflictError("Capture found multiple sources; inspect and choose a video")
            job.request.media_candidates = candidates
            # Captions from a page-wide capture are ambiguous with multiple videos.
            if len(payload.media_candidates) == 1 and payload.caption_candidates:
                job.request.caption_candidates = payload.caption_candidates
            job.request.browser_context = payload.browser_context
            job.status = JobStatus.QUEUED
            job.phase = JobPhase.DOWNLOAD
            job.progress = 0.0
            job.message = "Queued with captured browser request"
            job.error_code = None
            job.can_capture = False
            job.acquisition_mode = "captured_request"
            job.cancel_event.clear()
            self._persist(job)
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
                if self._persist(job):
                    del self._jobs[job_id]
            return response

    def _require(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise JobNotFoundError("Video job was not found") from error

    def _persist(self, job: _Job) -> bool:
        """Mirror this job's externally meaningful state into `video_jobs`, best-effort.

        Status, phase, progress, message, error code and video_id are the whole of what
        that table carries (`migrations/0018_video_jobs.sql`) -- everything else about a
        job is local-machine detail nothing sharing the database needs. Skipped outright
        without a configured database, and logged rather than raised on failure: this is a
        mirror for other readers, and losing the write must not cost the job itself, which
        by the time this runs has already gotten further than this write has.

        Returns whether the row actually landed, which is what a caller deciding whether a
        terminal job can safely leave `self._jobs` needs to know: without it, or if it
        failed, this dictionary is the only place that job's outcome still exists.
        """
        if not is_postgres_configured():
            return False
        try:
            PostgresVideoJobs().upsert(
                VideoJob(
                    id=job.job_id,
                    page_url=job.request.page_url,
                    page_title=job.request.page_title,
                    status=job.status.value,
                    phase=job.phase.value,
                    progress=job.progress,
                    message=job.message,
                    user_id=job.user_id,
                    video_id=job.video_id,
                    acquisition_mode=job.acquisition_mode,
                    error_code=job.error_code,
                )
            )
            return True
        except Exception:
            logger.exception("Persisting job %s to the database failed", job.job_id)
            return False

    def _progress(self, job_id: str, phase: JobPhase, value: float, message: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.phase = phase
            job.progress = min(max(value, 0.0), 1.0)
            job.message = message
            self._persist(job)

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

        Everything the run writes goes in its own workspace folder, and the folder is deleted
        once the run ends, whatever ended it. A file Chrome downloaded is moved in first, so
        it goes with the rest.
        """
        with self._lock:
            job = self._require(job_id)
            if job.status == JobStatus.CANCELLED:
                if local_path is not None:
                    _delete_local_path(local_path)
                return
            job.status = JobStatus.RUNNING
            request, acquisition_mode, user_id = job.request, job.acquisition_mode, job.user_id
        workspace = self._job_workspaces / job_id
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            if local_path is not None:
                local_path = Path(shutil.move(local_path, workspace / local_path.name))
            processed = run_download_pipeline(
                ROUTE_BY_ACQUISITION_MODE[acquisition_mode],
                request=request,
                download_root=workspace,
                job_id=job_id,
                acquisition_mode=acquisition_mode,
                cancel_event=job.cancel_event,
                progress_callback=lambda phase, value, message: self._progress(
                    job_id, phase, value, message
                ),
                user_id=user_id,
                local_path=local_path,
                schedule_visual_indexing=(
                    self._schedule_visual_indexing if config.visual_indexing_enabled() else None
                ),
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
            )
        else:
            self._finish(job_id, processed)
        finally:
            _delete_local_path(workspace)

    def _schedule_visual_indexing(self, video_id: str, local_path: Path) -> None:
        """Queue one stored video's visual index on the visual executor, which now owns its file.

        The file moves out of its job's workspace into the visual queue first, because the
        workspace is deleted when the run ends and the index is built after that. The task
        deletes the local file itself when it ends. A task that never starts --
        cancelled because the manager shut down first -- cannot, so the future's callback
        does it instead, and marks the video interrupted so the next start builds its index
        from Blob Storage. The task reads keyframe text with the machine's OCR engine, when
        one is set up; the engine and its worker process are shared by every video.
        """
        self._visual_indexing_queue.mkdir(parents=True, exist_ok=True)
        # A name of its own rather than the video id's, so indexing one video twice cannot
        # overwrite a copy the first task is still reading.
        local_path = Path(
            shutil.move(
                local_path, self._visual_indexing_queue / f"{uuid.uuid4().hex}{local_path.suffix}"
            )
        )
        future = self._visual_executor.submit(
            index_video_visually,
            video_id,
            local_path,
            stop_event=self._visual_stop,
            ocr_engine=configured_ocr_engine(),
        )

        def delete_if_never_run(finished: Future) -> None:
            if finished.cancelled():
                local_path.unlink(missing_ok=True)
            _mark_if_never_run(video_id, finished)

        future.add_done_callback(delete_if_never_run)

    def _queue_interrupted_visual_indexing(self) -> None:
        """Claim the interrupted indexes and queue each one; runs on the visual executor."""
        try:
            video_ids = claim_interrupted_visual_indexing()
        except Exception:
            logger.exception("Looking for interrupted visual indexes to resume failed")
            return
        for video_id in video_ids:
            logger.info("Indexing video %s visually again, after an interrupted run", video_id)
            try:
                future = self._visual_executor.submit(
                    reindex_video_visually,
                    video_id,
                    self._visual_indexing_queue,
                    stop_event=self._visual_stop,
                    ocr_engine=configured_ocr_engine(),
                )
            except RuntimeError:
                # The manager shut down while these were being claimed.
                mark_visual_indexing_never_run(video_id)
                continue
            future.add_done_callback(
                lambda finished, video_id=video_id: _mark_if_never_run(video_id, finished)
            )

    def _fail_acquisition(
        self,
        job_id: str,
        error: Exception,
        *,
        acquisition_mode: str,
        can_capture: bool,
    ) -> None:
        """Report a run that never got as far as a stored video, in the route's own terms.

        A file Chrome already downloaded was obtained, so what failed was processing it. The
        file went with the run's workspace: nothing would ever have read it again.
        """
        if acquisition_mode == "browser_download":
            self._fail(
                job_id,
                PROCESSING_FAILED,
                f"Processing the Chrome download failed ({type(error).__name__})",
                can_capture=False,
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
            # The video now lives in Blob Storage and its transcript and comments in the
            # database. The local files made on the way go with the run's workspace -- the
            # video once visual indexing is done with it -- so no path is reported.
            job.video_path = None
            job.transcript_source = acquired.transcript_source
            job.video_storage_key = processed.stored_video.name
            job.video_id = processed.video_id
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
            # COMPLETE and PARTIAL_SUCCESS are both dead ends -- neither is eligible for
            # `retry_with_capture` -- so nothing this process still holds about the job is
            # needed again once the database has a durable copy of its outcome. Without one
            # configured, or if the write failed, this dictionary stays the only record of
            # it, so eviction only follows a persist that actually landed.
            if self._persist(job):
                del self._jobs[job_id]

    def _fail(
        self,
        job_id: str,
        code: str,
        message: str,
        *,
        can_capture: bool,
    ) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = JobStatus.FAILED
            job.error_code = code
            job.message = message
            job.can_capture = can_capture
            self._discard_secrets(job_id)
            # FAILED, unlike the finished statuses, is not evicted: `retry_with_capture`
            # accepts a captured request for exactly this status, and needs the same `_Job`
            # -- its caption text kept for the retry, among other things -- still in the
            # dictionary.
            self._persist(job)

    def _mark_cancelled(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled"
            job.can_capture = False
            self._discard_secrets(job_id)
            if self._persist(job):
                del self._jobs[job_id]

    def _discard_secrets(self, job_id: str) -> None:
        """Clear this job's browser-supplied secrets.

        Always called from inside the same lock acquisition that publishes the job's
        terminal status (`_fail`, `_mark_cancelled`, `_finish`, and `cancel`'s own inline
        transition to CANCELLED) rather than afterwards. Otherwise a `retry_with_capture`
        call landing between the status write and this cleanup would install fresh
        captured cookies/headers just in time for this call to wipe them instead of the
        stale ones it was meant to discard. `self._lock` is reentrant, so nesting here is
        safe. `_persist` and the dictionary eviction that follows it in each of those
        callers stay under the same acquisition for the same reason: a retry that found the
        job still present must find it exactly as this method left it.
        """
        with self._lock:
            job = self._require(job_id)
            job.request.browser_context.cookies.clear()
            job.request.browser_context.headers.clear()
            for candidate in job.request.media_candidates:
                candidate.headers.clear()
            if not job.can_capture:
                job.request.structured_candidates.clear()
                for caption in job.request.caption_candidates:
                    caption.text = None
