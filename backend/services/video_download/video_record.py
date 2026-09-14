"""Records a finished job's video and transcript in Supabase, once its file is in R2.

This runs after the upload rather than beside it, because the row describes an object that
exists: `r2_object_key` is the whole point of the row, and there is no key to write until
the upload has returned one. A job whose upload was skipped or failed therefore records
nothing, which is the honest outcome — the video is on one machine, and the table is for
videos that outlived it.

The two writes are ordered and not one transaction. The video row goes first because the
segments reference it, and a video recorded without its transcript is a coherent state
that a later run can fix by writing the segments; segments with no video are not a state
the database will accept at all.

A checkout with no Supabase credentials skips both writes and keeps working, the same way
one with no R2 credentials skips the upload.
"""

from __future__ import annotations

import logging

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.transcripts import NormalizedTranscript
from backend.storage.r2 import StoredVideo
from backend.storage.supabase import (
    StoredVideoRecord,
    SupabaseTranscriptSegments,
    SupabaseVideoRecords,
    VideoRecord,
    is_supabase_configured,
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
) -> StoredVideoRecord | None:
    """Write the video's row and its transcript, or None when no project is configured.

    `duration_seconds` and `source_video_id` are left unset: neither pipeline reports them
    today, and guessing them from a filename would put something in the table that nobody
    measured. The transcript's own duration is not borrowed for the video's either — it is
    where the last person stopped talking, which is not where the video ends.
    """
    if not is_supabase_configured():
        logger.info("No Supabase project configured; %s is stored but unrecorded", stored_video.key)
        return None

    stored = SupabaseVideoRecords().upsert(
        VideoRecord(
            source=acquisition_mode,
            source_url=request.page_url,
            title=request.page_title,
            r2_bucket=stored_video.bucket,
            r2_object_key=stored_video.key,
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
        SupabaseTranscriptSegments().replace(stored.id, transcript.segments)
    return stored
