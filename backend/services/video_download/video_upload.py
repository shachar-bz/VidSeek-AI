"""Puts a finished job's video into the Blob Storage container, as the job's last phase.

The upload runs after transcription rather than straight after the download, so that one
place in the job manager owns it for all three routes — YouTube, authenticated download
and a file Chrome fetched — instead of each pipeline growing its own copy.

Blob Storage is the video's only home: the local copy made during download exists solely to
get the video transcribed, and is deleted once it is safely in the container. A checkout
with no storage credentials cannot give a video anywhere durable to live, so it fails the
job instead of letting the local file quietly become the permanent copy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.schemas.video_jobs import JobPhase
from backend.storage.blob import BlobVideoStorage, StoredVideo

# The slice of a job's progress bar the upload owns. Everything before it reports up to
# 0.85, and the job manager sets 1.0 once the result is recorded.
PROGRESS_START = 0.9
PROGRESS_END = 0.99

UPLOAD_MESSAGE = "Uploading video to Azure Blob Storage"

logger = logging.getLogger(__name__)


def upload_job_video(
    *,
    video_path: Path,
    job_id: str,
    progress_callback,
) -> StoredVideo:
    """Upload one job's video to Blob Storage, then delete the local copy, raising on any failure.

    The job id is the video's prefix in the container. It is what the companion has to hand
    that is unique per video; the `videos` row written afterwards is what ties this blob
    name to the page the video came from.
    """
    storage = BlobVideoStorage()
    progress_callback(JobPhase.UPLOAD, PROGRESS_START, UPLOAD_MESSAGE)
    stored = storage.upload_video(
        video_path,
        video_id=job_id,
        progress_callback=lambda uploaded, total: progress_callback(
            JobPhase.UPLOAD,
            PROGRESS_START + (PROGRESS_END - PROGRESS_START) * (uploaded / total if total else 1.0),
            UPLOAD_MESSAGE,
        ),
    )
    video_path.unlink(missing_ok=True)
    return stored
