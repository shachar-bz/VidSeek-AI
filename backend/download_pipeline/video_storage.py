"""Stage two: put the video somewhere durable, and describe it in the database.

The two halves fail differently and that asymmetry is the whole content of this module.
Blob Storage is the video's only home — the local copy was made to get the video
transcribed and is deleted as soon as the upload returns — so a container that will not
take it leaves the run with nothing, and `VideoStorageError` says so. The `videos` row is
a description of a blob that already exists, and can be written again later from the blob
name alone, so a database that refuses it is reported and the run carries on.

Everything after this stage is keyed on the `videos` row's id: memories, chapters and both
kinds of vector all point at it. That is why this stage returns the id rather than just a
blob name, and why a run with no id has nowhere to put anything the later stages produce.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.core.security import probe_media_duration_seconds
from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.video_download.video_record import record_job_video
from backend.services.video_download.video_upload import upload_job_video
from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.blob import StoredVideo

from .result import RECORD_FAILED, VideoStorageError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageOutcome:
    """Where the video ended up, and whether the database heard about it.

    `video_id` is None both when the write failed and when there is no database configured
    at all. The two are told apart by `problem`, which is set only for the failure: a
    checkout with no database is expected to work, and reporting it as a problem would make
    every local run look broken.
    """

    stored_video: StoredVideo
    video_id: str | None
    problem: str | None = None


def store_video(
    *,
    acquired: PipelineResult,
    request: CreateVideoJobRequest,
    job_id: str,
    acquisition_mode: str,
    user_id: str | None = None,
    progress_callback,
) -> StorageOutcome:
    """Upload the video and record it, raising only if the upload itself fails.

    `acquisition_mode` is the job manager's own name for how the video was obtained, and is
    written to the row as its `source`; it is passed through rather than derived from the
    route so that the value the extension was told matches the value the database keeps.

    Duration is probed here, on `acquired.video_path`, because this is the last point that
    file still exists: `upload_job_video` deletes the local copy the moment the upload
    returns. A file ffprobe cannot measure still gets stored -- `probe_media_duration_seconds`
    reports that as None rather than raising, and a video is worth keeping with or without
    its length.
    """
    duration_seconds = probe_media_duration_seconds(acquired.video_path)
    try:
        stored_video = upload_job_video(
            video_path=acquired.video_path,
            job_id=job_id,
            progress_callback=progress_callback,
        )
    except Exception as error:
        logger.exception("Storing %s in Blob Storage failed", acquired.video_path)
        raise VideoStorageError(str(error)) from error

    try:
        recorded = record_job_video(
            stored_video=stored_video,
            request=request,
            job_id=job_id,
            acquisition_mode=acquisition_mode,
            transcript_source=acquired.transcript_source,
            transcript=acquired.normalized_transcript,
            comments=acquired.comments,
            user_id=user_id,
            duration_seconds=duration_seconds,
        )
    except Exception:
        logger.exception("Recording %s in the database failed", stored_video.name)
        return StorageOutcome(stored_video=stored_video, video_id=None, problem=RECORD_FAILED)

    return StorageOutcome(
        stored_video=stored_video,
        video_id=recorded.id if recorded else None,
    )
