"""The visual stage: a stored video is indexed for what it shows, in the background, from its local file.

Unlike the other stages this one is not a step of `run_download_pipeline`. Right after Store,
the pipeline hands the video to `hand_over_for_visual_indexing`, which gives it to the job
manager's visual executor and returns at once; the transcript stages carry on in parallel, and
the job reports done when they do. `index_video_visually` is the task that executor runs.

The task owns the local video file. Store no longer deletes it, because the index is built from
that copy rather than from Blob Storage; the task deletes it in a `finally`, so it goes whether
indexing succeeded, failed or was skipped. When no task will run -- no video row, a cancelled
job, visual indexing turned off -- the hand-over deletes it instead, straight away.

Nothing here can fail the job, which has usually finished by the time this runs. Every outcome
is written to `videos.visual_status` instead (`pending` -> `indexing` -> `ready` | `failed` |
`skipped`), with a short code in `visual_error` saying why a video has no index.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.core.security import probe_media_duration_seconds
from backend.services.visual_indexing import (
    CURRENT_VISUAL_INDEX_VERSION,
    NoFramesToIndex,
    SamplingStopped,
    build_visual_index,
)
from backend.storage.postgres import NewFrameEmbedding, NewVisualSegment, PostgresVisualIndex
from backend.storage.postgres.visual_index import FAILED, INDEXING, READY, SKIPPED

# Why a video has no visual index, as `videos.visual_error` records it.
VISUAL_INDEXING_FAILED = "visual_indexing_failed"
VISUAL_INDEXING_INTERRUPTED = "visual_indexing_interrupted"
VISUAL_INDEXING_DISABLED = "visual_indexing_disabled"
VISUAL_INDEXING_NOT_SCHEDULED = "visual_indexing_not_scheduled"
JOB_CANCELLED = "job_cancelled"
NO_VIDEO_FRAMES = "no_video_frames"

# What the job manager passes in to run a task on its visual executor. It returns at once.
ScheduleVisualIndexing = Callable[[str, Path], None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualIndexingOutcome:
    """Where one video's visual index ended up, and how much of it there is."""

    status: str
    problem: str | None = None
    frame_count: int = 0
    segment_count: int = 0


def hand_over_for_visual_indexing(
    video_id: str | None,
    local_path: Path,
    *,
    schedule: ScheduleVisualIndexing | None,
    cancel_event: threading.Event,
    pool=None,
) -> None:
    """Give the stored video to the visual executor, or delete its local copy if nothing will.

    Called right after Store, whatever the transcript stages are about to do: the index is
    built from pictures, so a video whose transcript failed can still be indexed. `schedule`
    is None when visual indexing is turned off on this machine.
    """
    if video_id is None:
        # No row to hang an index off; Store already reported why when that is a problem.
        _delete_local_copy(local_path)
        return
    if cancel_event.is_set():
        _skip(video_id, local_path, JOB_CANCELLED, pool=pool)
        return
    if schedule is None:
        _skip(video_id, local_path, VISUAL_INDEXING_DISABLED, pool=pool)
        return
    try:
        schedule(video_id, local_path)
    except Exception:
        logger.exception("Scheduling visual indexing for video %s failed", video_id)
        _skip(video_id, local_path, VISUAL_INDEXING_NOT_SCHEDULED, pool=pool)


def index_video_visually(
    video_id: str,
    local_path: Path,
    *,
    stop_event: threading.Event | None = None,
    pool=None,
    embed_images=None,
) -> VisualIndexingOutcome:
    """Build and store one video's visual index, then delete the local file whatever happened.

    Returns the outcome rather than raising: it runs on an executor nobody waits on, so an
    exception would vanish into a future. `stop_event` is the job manager shutting down;
    indexing stops at the next frame and the video is marked failed as interrupted.
    `embed_images` is for a test to stand in for SigLIP.
    """
    store = PostgresVisualIndex(pool=pool)
    try:
        _mark(store, video_id, INDEXING)
        built = build_visual_index(
            local_path,
            duration_seconds=probe_media_duration_seconds(local_path),
            embed_images=embed_images,
            stop_event=stop_event,
        )
        store.replace(
            video_id,
            frames=[
                NewFrameEmbedding(time_seconds=frame.time_seconds, embedding=frame.embedding.tolist())
                for frame in built.frames
            ],
            segments=[
                NewVisualSegment(
                    segment_index=segment.index,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    boundary_kind=segment.boundary_kind,
                    keyframe_times=segment.keyframe_times,
                )
                for segment in built.segments
            ],
            index_version=CURRENT_VISUAL_INDEX_VERSION,
        )
        return VisualIndexingOutcome(
            status=READY, frame_count=len(built.frames), segment_count=len(built.segments)
        )
    except NoFramesToIndex:
        logger.warning("Video %s decoded to no frames; nothing to index visually", video_id)
        _mark(store, video_id, SKIPPED, error=NO_VIDEO_FRAMES)
        return VisualIndexingOutcome(status=SKIPPED, problem=NO_VIDEO_FRAMES)
    except SamplingStopped:
        logger.info("Visual indexing of video %s was interrupted", video_id)
        _mark(store, video_id, FAILED, error=VISUAL_INDEXING_INTERRUPTED)
        return VisualIndexingOutcome(status=FAILED, problem=VISUAL_INDEXING_INTERRUPTED)
    except Exception:
        logger.exception("Visual indexing of video %s failed", video_id)
        _mark(store, video_id, FAILED, error=VISUAL_INDEXING_FAILED)
        return VisualIndexingOutcome(status=FAILED, problem=VISUAL_INDEXING_FAILED)
    finally:
        _delete_local_copy(local_path)


def _skip(video_id: str, local_path: Path, reason: str, *, pool) -> None:
    """Record that no index will be built for this video, and drop its local copy."""
    _mark(PostgresVisualIndex(pool=pool), video_id, SKIPPED, error=reason)
    _delete_local_copy(local_path)


def _mark(store: PostgresVisualIndex, video_id: str, status: str, *, error: str | None = None) -> None:
    """Write a status change, logging rather than raising if the database refuses it.

    A status that could not be written leaves the row saying something stale, which is
    worth a log line; it is not worth losing the index that was just built, or skipping the
    deletion of the local file that follows.
    """
    try:
        store.mark(video_id, status, error=error)
    except Exception:
        logger.exception("Recording visual status %s for video %s failed", status, video_id)


def _delete_local_copy(local_path: Path) -> None:
    """Delete the local video file; the video lives on in Blob Storage."""
    try:
        local_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Deleting the local copy %s failed", local_path)
