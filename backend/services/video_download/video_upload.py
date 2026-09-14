"""Puts a finished job's video into the R2 bucket, as the job's last phase.

The upload runs after transcription rather than straight after the download, so that one
place in the job manager owns it for all three routes — YouTube, authenticated download
and a file Chrome fetched — instead of each pipeline growing its own copy.

The local file is left where it is. The extension shows its path, and R2 is a second
home for the video rather than a replacement for the download folder.

A checkout with no R2 credentials skips the upload and keeps working, because a video
that is downloaded and transcribed but not uploaded is still most of what a job is for.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.schemas.video_jobs import JobPhase
from backend.storage.r2 import R2VideoStorage, StoredVideo, is_r2_configured

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
) -> StoredVideo | None:
    """Upload one job's video, or return None when there is no bucket configured.

    The job id is the video's prefix in the bucket. It is what the companion has to hand
    that is unique per video; once Supabase holds the metadata, its row will be what ties
    this key to the page the video came from.
    """
    if not is_r2_configured():
        logger.info("No R2 bucket configured; %s stays on this machine", video_path.name)
        return None

    progress_callback(JobPhase.UPLOAD, PROGRESS_START, "Uploading video to R2")
    stored = R2VideoStorage().upload_video(
        video_path,
        video_id=job_id,
        progress_callback=lambda uploaded, total: progress_callback(
            JobPhase.UPLOAD,
            PROGRESS_START + (PROGRESS_END - PROGRESS_START) * (uploaded / total if total else 1.0),
            "Uploading video to R2",
        ),
    )
    return stored
