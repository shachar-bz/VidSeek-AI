"""Records a finished job's video, transcript and comments in PostgreSQL, once its file is
in Blob Storage.

This runs after the upload rather than beside it, because the row describes a blob that
exists: `blob_name` is the whole point of the row, and there is no name to write until the
upload has returned one. A job whose upload fails never reaches this at all — Blob Storage
is the video's only home, so that failure fails the job outright rather than leaving
anything here to record.

The writes are ordered and not one transaction. The video row goes first because the
transcript and comments reference it, and a video recorded without either is a coherent
state that a later run can fix by writing them; either with no video is not a state the
database will accept at all.

A checkout with no database configured skips every write and keeps working. Unlike Blob
Storage, that is not fatal: the video is already durable in the container, and the row can
always be written later from the blob name alone.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.transcripts import NormalizedTranscript
from backend.services.video_download.youtube.comments import CommentEntry
from backend.storage.blob import StoredVideo
from backend.storage.postgres import (
    PostgresComments,
    PostgresTranscriptSegments,
    PostgresVideoRecords,
    StoredVideoRecord,
    VideoRecord,
    is_postgres_configured,
)

logger = logging.getLogger(__name__)


def record_job_video(
    *,
    stored_video: StoredVideo,
    request: CreateVideoJobRequest,
    job_id: str,
    acquisition_mode: str,
    transcript_source: str | None,
    transcript: NormalizedTranscript | None = None,
    comments: Sequence[CommentEntry] | None = None,
    user_id: str | None = None,
) -> StoredVideoRecord | None:
    """Write the video's row, transcript and comments, or None when no database is configured.

    `duration_seconds` and `source_video_id` are left unset: neither pipeline reports them
    today, and guessing them from a filename would put something in the table that nobody
    measured. The transcript's own duration is not borrowed for the video's either — it is
    where the last person stopped talking, which is not where the video ends.

    `comments` is None for every pipeline but YouTube's, which is the only one with
    anything to fetch; an empty sequence still means something (the fetch ran and found
    nothing) and is written as that, clearing any comments a previous run left behind.

    `user_id` is None for a job the route never had a signed-in account for; the row is
    still worth writing, just without an owner.
    """
    if not is_postgres_configured():
        logger.info("No database configured; %s is stored but unrecorded", stored_video.name)
        return None

    stored = PostgresVideoRecords().upsert(
        VideoRecord(
            source=acquisition_mode,
            source_url=request.page_url,
            title=request.page_title,
            blob_container=stored_video.container,
            blob_name=stored_video.name,
            user_id=user_id,
            file_size_bytes=stored_video.size_bytes,
            content_type=stored_video.content_type,
            transcript_source=transcript_source,
            transcript_language=transcript.language if transcript else None,
            transcript_timing_fidelity=(
                transcript.timing_fidelity.value if transcript else None
            ),
            job_id=job_id,
        )
    )
    if transcript is not None:
        PostgresTranscriptSegments().replace(stored.id, transcript.segments)
    if comments is not None:
        PostgresComments().replace(stored.id, comments)
    return stored
