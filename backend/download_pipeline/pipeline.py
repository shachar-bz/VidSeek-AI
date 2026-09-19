"""The five stages from a captured video URL to durable, searchable generated artifacts.

1. Acquire — download the video and get a timed transcript beside it, whichever of the
   three ways it has to be obtained (`acquisition`).
2. Store — upload the video to Blob Storage, and describe it, its transcript and its
   comments in the database (`video_storage`).
3. Segment — divide the transcript into memories, group those into chapters, store both
   (`segmentation`).
4. Embed — turn the memories and chapters into vectors (`embedding`).
5. Insights — generate the video's summary, takeaways and suggested questions (`insights`).

Each stage is a module of its own and each one is callable on its own; this is only the
order and the handover between them. This module performs no stage work itself; each stage
delegates generation or processing to a service and owns only its durable handoff.

The stages divide at a sharp line. The first two either produce a video that exists
somewhere durable or raise, because there is no half of a video worth keeping. The last three
describe a video that is already safe, so they report what they could not do and the run
finishes anyway: the codes come back on `ProcessedVideo.problems`, and re-running any such
stage later needs nothing this process still holds.

Cancellation is checked between stages, which is the same granularity the download services
offer: a stage that has started runs to completion, and the run stops at the next boundary.
Where it stops changes once the video is stored, though. Before then a cancel raises and the
run has no result, which is right because there is nothing to report. Afterwards the video is
in Blob Storage whatever anyone now wants, so a cancel skips the remaining model-driven stages and
the run returns what it has -- reporting a stored video as cancelled would be untrue, and
spending several minutes of model time on a video somebody asked to stop would be worse.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from yt_dlp.utils import DownloadCancelled

from backend.schemas.video_jobs import CreateVideoJobRequest, JobPhase

from .acquisition import AcquisitionRoute, acquire_video
from .embedding import embed_video
from .insights import generate_and_store_insights
from .result import ProcessedVideo
from .segmentation import segment_and_store
from .video_storage import store_video

SEGMENTATION_PROGRESS = 0.92
SEGMENTATION_MESSAGE = "Finding the video's moments and chapters"

EMBEDDING_PROGRESS = 0.97
EMBEDDING_MESSAGE = "Making the video searchable"

INSIGHTS_PROGRESS = 0.99
INSIGHTS_MESSAGE = "Generating video insights"

logger = logging.getLogger(__name__)


def run_download_pipeline(
    route: AcquisitionRoute,
    *,
    request: CreateVideoJobRequest,
    download_root: Path,
    job_id: str,
    acquisition_mode: str,
    cancel_event: threading.Event,
    progress_callback,
    user_id: str | None = None,
    local_path: Path | None = None,
    pool=None,
) -> ProcessedVideo:
    """Take one video from `route` to stored vectors and generated insights.

    Raises `DownloadCancelled` if the run was cancelled at a stage boundary,
    `VideoStorageError` if Blob Storage would not take the video, and whatever the download
    service raised if the video could not be obtained at all. Every other failure comes back
    as a problem code on the result.

    `pool` is threaded through to the stages that write to PostgreSQL so a test can point
    them at its own database; it is None everywhere else, which uses the shared pool.
    """
    acquired = acquire_video(
        route,
        request=request,
        download_root=download_root,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
        local_path=local_path,
    )
    _raise_if_cancelled(cancel_event)

    storage = store_video(
        acquired=acquired,
        request=request,
        job_id=job_id,
        acquisition_mode=acquisition_mode,
        user_id=user_id,
        progress_callback=progress_callback,
    )
    problems = [storage.problem] if storage.problem else []

    reason = _reason_to_stop_after_storage(acquired, storage.video_id, cancel_event)
    if reason is not None:
        logger.info("Video %s is stored but not indexed: %s", storage.stored_video.name, reason)
        return ProcessedVideo(
            acquired=acquired,
            stored_video=storage.stored_video,
            video_id=storage.video_id,
            problems=tuple(problems),
        )

    progress_callback(JobPhase.SEGMENTATION, SEGMENTATION_PROGRESS, SEGMENTATION_MESSAGE)
    segmented = segment_and_store(
        storage.video_id, acquired.normalized_transcript, pool=pool
    )
    problems.extend(segmented.problems)

    if segmented.memory_count == 0 or cancel_event.is_set():
        return ProcessedVideo(
            acquired=acquired,
            stored_video=storage.stored_video,
            video_id=storage.video_id,
            memory_count=segmented.memory_count,
            chapter_count=segmented.chapter_count,
            problems=tuple(problems),
        )

    progress_callback(JobPhase.EMBEDDING, EMBEDDING_PROGRESS, EMBEDDING_MESSAGE)
    embedded = embed_video(storage.video_id, pool=pool)
    problems.extend(embedded.problems)

    if cancel_event.is_set():
        return ProcessedVideo(
            acquired=acquired,
            stored_video=storage.stored_video,
            video_id=storage.video_id,
            memory_count=segmented.memory_count,
            chapter_count=segmented.chapter_count,
            memory_embedding_count=embedded.memory_count,
            chapter_embedding_count=embedded.chapter_count,
            problems=tuple(problems),
        )

    progress_callback(JobPhase.INSIGHTS, INSIGHTS_PROGRESS, INSIGHTS_MESSAGE)
    insights = generate_and_store_insights(storage.video_id, pool=pool)
    problems.extend(insights.problems)

    return ProcessedVideo(
        acquired=acquired,
        stored_video=storage.stored_video,
        video_id=storage.video_id,
        memory_count=segmented.memory_count,
        chapter_count=segmented.chapter_count,
        memory_embedding_count=embedded.memory_count,
        chapter_embedding_count=embedded.chapter_count,
        problems=tuple(problems),
    )


def _reason_to_stop_after_storage(
    acquired, video_id: str | None, cancel_event: threading.Event
) -> str | None:
    """Why stages three through five will not run, or None when they will. For the log line only.

    Nothing is added to `problems` for any of these, because whatever a caller needs to know
    is already there. No `videos` row means either a write that failed, which is already
    reported as `RECORD_FAILED`, or a checkout with no database configured, which is an
    expected way to run and not a problem with the video. No timed transcript means the
    download stage already set `transcript_error`, and saying the same thing a second time
    under a different name would only make a job look twice as broken as it is. A cancelled
    run is not a problem with the video at all.
    """
    if video_id is None:
        return "no video row to hang memories, chapters or vectors off"
    if acquired.normalized_transcript is None:
        return "no timed transcript to divide into memories"
    if cancel_event.is_set():
        return "the job was cancelled once the video was safely stored"
    return None


def _raise_if_cancelled(cancel_event: threading.Event) -> None:
    """Stop between stages; each one runs to completion once started."""
    if cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")
