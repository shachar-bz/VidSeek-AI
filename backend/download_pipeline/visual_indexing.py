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

Once the index is stored and `ready`, the task reads the on-screen text of its keyframes with
the OCR engine it was given, while the local file still exists, and writes each batch onto
the keyframe rows as it is read. This comes last because it is the slow part: the video is
searchable by its frames the whole time. OCR cannot fail the index either. A keyframe it did
not reach keeps no engine on its row, which is how an unread keyframe is told apart from one
that shows no text; with no engine configured, every keyframe is left that way.
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
    read_keyframe_text,
)
from backend.services.ocr import OcrEngine
from backend.services.visual_indexing.segments import VisualSegment
from backend.storage.postgres import (
    KeyframeText,
    NewFrameEmbedding,
    NewVisualSegment,
    PostgresVisualIndex,
)
from backend.storage.postgres.visual_index import FAILED, INDEXING, READY, SKIPPED

# Why a video has no visual index, as `videos.visual_error` records it.
VISUAL_INDEXING_FAILED = "visual_indexing_failed"
VISUAL_INDEXING_INTERRUPTED = "visual_indexing_interrupted"
VISUAL_INDEXING_DISABLED = "visual_indexing_disabled"
VISUAL_INDEXING_NOT_SCHEDULED = "visual_indexing_not_scheduled"
JOB_CANCELLED = "job_cancelled"
NO_VIDEO_FRAMES = "no_video_frames"

# Why an index that is `ready` has keyframes whose text was not read. Reported in the outcome
# and the log only: the index itself is fine, and `visual_error` is for an index that is not.
OCR_FAILED = "ocr_failed"
OCR_INTERRUPTED = "ocr_interrupted"

# What the job manager passes in to run a task on its visual executor. It returns at once.
ScheduleVisualIndexing = Callable[[str, Path], None]

# Turns on-screen texts into multilingual-e5-small vectors, in order.
EmbedTexts = Callable[[list[str]], list[list[float]]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualIndexingOutcome:
    """Where one video's visual index ended up, and how much of it there is."""

    status: str
    problem: str | None = None
    frame_count: int = 0
    segment_count: int = 0
    # How many keyframes OCR read, and how many of those show text.
    keyframes_read: int = 0
    keyframes_with_text: int = 0
    # Why some keyframes were left unread although an OCR engine was given.
    ocr_problem: str | None = None


@dataclass(frozen=True)
class _TextReadingOutcome:
    keyframes_read: int = 0
    keyframes_with_text: int = 0
    problem: str | None = None


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
    ocr_engine: OcrEngine | None = None,
    embed_texts: EmbedTexts | None = None,
) -> VisualIndexingOutcome:
    """Build and store one video's visual index, read its keyframes' text, then delete the file.

    Returns the outcome rather than raising: it runs on an executor nobody waits on, so an
    exception would vanish into a future. `stop_event` is the job manager shutting down;
    indexing stops at the next frame and the video is marked failed as interrupted, or, once
    the index is stored, OCR stops at the next batch. `ocr_engine` None leaves every keyframe
    unread. `embed_images` and `embed_texts` are for a test to stand in for SigLIP and e5.
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
        text_reading = _read_on_screen_text(
            store,
            video_id,
            local_path,
            built.segments,
            engine=ocr_engine,
            embed_texts=embed_texts,
            stop_event=stop_event,
        )
        return VisualIndexingOutcome(
            status=READY,
            frame_count=len(built.frames),
            segment_count=len(built.segments),
            keyframes_read=text_reading.keyframes_read,
            keyframes_with_text=text_reading.keyframes_with_text,
            ocr_problem=text_reading.problem,
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


def _read_on_screen_text(
    store: PostgresVisualIndex,
    video_id: str,
    local_path: Path,
    segments: tuple[VisualSegment, ...],
    *,
    engine: OcrEngine | None,
    embed_texts: EmbedTexts | None,
    stop_event: threading.Event | None,
) -> _TextReadingOutcome:
    """Read every keyframe's text and store it batch by batch; never raises.

    The index is already `ready`, so a failure here costs only the text not yet read: what
    was stored before it stays, and the keyframes after it keep no engine on their rows.
    """
    if engine is None:
        logger.info("No OCR engine is set up; the keyframes of video %s are left unread", video_id)
        return _TextReadingOutcome()
    embed_texts = embed_texts or _embed_with_e5
    keyframe_times = [time_seconds for segment in segments for time_seconds in segment.keyframe_times]
    read = with_text = 0
    try:
        for batch in read_keyframe_text(local_path, keyframe_times, engine, stop_event=stop_event):
            shown = [reading.text for reading in batch if reading.text is not None]
            vectors = iter(embed_texts([text.text for text in shown]) if shown else ())
            store.set_keyframe_text(
                video_id,
                [
                    KeyframeText(
                        time_seconds=reading.time_seconds,
                        text=reading.text.text,
                        language=reading.text.language,
                        confidence=reading.text.confidence,
                        embedding=next(vectors),
                    )
                    if reading.text is not None
                    else KeyframeText(time_seconds=reading.time_seconds, text=None)
                    for reading in batch
                ],
                engine=engine.name,
            )
            read += len(batch)
            with_text += len(shown)
    except SamplingStopped:
        logger.info("Reading the on-screen text of video %s was interrupted", video_id)
        return _TextReadingOutcome(read, with_text, OCR_INTERRUPTED)
    except Exception:
        logger.exception(
            "Reading the on-screen text of video %s failed after %d keyframes", video_id, read
        )
        return _TextReadingOutcome(read, with_text, OCR_FAILED)
    return _TextReadingOutcome(read, with_text)


def _embed_with_e5(texts: list[str]) -> list[list[float]]:
    """multilingual-e5-small passage vectors, the model loaded only once there is text to embed."""
    from backend.services.embeddings.multilingual_text_embedding import embed_passages

    return embed_passages(texts)


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
