"""The video job lifecycle: create, poll, hand over a Chrome download, retry, cancel.

The status each failure maps to is preserved exactly as it was before these routes were
split out of one module, including one asymmetry that is inherited rather than intended:
`/capture` reports a bad media URL as 409 because it maps every ValueError to a conflict,
while `/v1/video-jobs` reports the same rejection as 422. Fixing that changes the contract
the extension is written against, so it belongs in its own step rather than in a move.

The handlers still catch `ValueError` rather than the narrower names in `core.errors`,
because those names subclass it and catching the builtin is what today's statuses are
built on. The named exceptions are what a later narrowing will switch to.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies import authorize, current_user_for_job_creation, job_manager
from backend.core.errors import (
    JobNotFoundError,
    MissingDependencyError,
    UnsupportedMediaError,
)
from backend.schemas.video_jobs import (
    BrowserDownloadCompleteRequest,
    CaptureRetryRequest,
    CreateVideoJobRequest,
    VideoJobResponse,
)
from backend.services.video_download.jobs import JobManager
from backend.storage.postgres import StoredUser

router = APIRouter(prefix="/v1/video-jobs", dependencies=[Depends(authorize)])

JOB_NOT_FOUND = "Video job was not found"


@router.post("", response_model=VideoJobResponse)
def create_job(
    payload: CreateVideoJobRequest,
    manager: JobManager = Depends(job_manager),
    user: StoredUser = Depends(current_user_for_job_creation),
) -> VideoJobResponse:
    try:
        return manager.create(payload, user_id=user.id)
    except (ValueError, UnsupportedMediaError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


@router.get("/{job_id}", response_model=VideoJobResponse)
def get_job(job_id: str, manager: JobManager = Depends(job_manager)) -> VideoJobResponse:
    try:
        return manager.get(job_id)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=JOB_NOT_FOUND
        ) from error


@router.post("/{job_id}/download-complete", response_model=VideoJobResponse)
def complete_download(
    job_id: str,
    payload: BrowserDownloadCompleteRequest,
    manager: JobManager = Depends(job_manager),
) -> VideoJobResponse:
    try:
        return manager.complete_browser_download(job_id, payload)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=JOB_NOT_FOUND
        ) from error
    except MissingDependencyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


@router.post("/{job_id}/capture", response_model=VideoJobResponse)
def retry_capture(
    job_id: str,
    payload: CaptureRetryRequest,
    manager: JobManager = Depends(job_manager),
) -> VideoJobResponse:
    try:
        return manager.retry_with_capture(job_id, payload)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=JOB_NOT_FOUND
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/{job_id}/cancel", response_model=VideoJobResponse)
def cancel_job(job_id: str, manager: JobManager = Depends(job_manager)) -> VideoJobResponse:
    try:
        return manager.cancel(job_id)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=JOB_NOT_FOUND
        ) from error
