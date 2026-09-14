"""Puts a finished job's video into the R2 bucket, as the job's last phase.

The upload runs after transcription rather than straight after the download, so that one
place in the job manager owns it for all three routes — YouTube, authenticated download
and a file Chrome fetched — instead of each pipeline growing its own copy.

R2 is the video's only home: the local copy made during download exists solely to get the
video transcribed, and is deleted once it is safely in the bucket. A checkout with no R2
credentials cannot give a video anywhere durable to live, so it fails the job instead of
letting the local file quietly become the permanent copy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.schemas.video_jobs import JobPhase
from backend.storage.r2 import R2VideoStorage, StoredVideo

# The slice of a job's progress bar the upload owns. Everything before it reports up to
# 0.85, and the job manager sets 1.0 once the result is recorded.
PROGRESS_START = 0.9
PROGRESS_END = 0.99

logger = logging.getLogger(__name__)


def upload_job_video(
    *,
    video_path: Path,
    job_id: str,
    progress_callback,
) -> StoredVideo:
    """Upload one job's video to R2, then delete the local copy, raising on any failure.

    The job id is the video's prefix in the bucket. It is what the companion has to hand
    that is unique per video; once Supabase holds the metadata, its row will be what ties
    this key to the page the video came from.
    """
    storage = R2VideoStorage()
    progress_callback(JobPhase.UPLOAD, PROGRESS_START, "Uploading video to R2")
    stored = storage.upload_video(
        video_path,
        video_id=job_id,
        progress_callback=lambda uploaded, total: progress_callback(
            JobPhase.UPLOAD,
            PROGRESS_START + (PROGRESS_END - PROGRESS_START) * (uploaded / total if total else 1.0),
            "Uploading video to R2",
        ),
    )
    video_path.unlink(missing_ok=True)
    return stored
