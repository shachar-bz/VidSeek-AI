"""Authenticated library listing, metadata edits, unlinking, dismissing failed jobs, tags, and progress events."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from backend.api.dependencies import current_user
from backend.core.page_titles import display_title
from backend.schemas.library import (
    LibraryPage,
    LibraryProgressEvent,
    LibraryQuery,
    LibrarySort,
    LibraryVideo,
    SortDirection,
    TagList,
    UpdateLibraryLinkRequest,
)
from backend.schemas.readiness import ReadinessStage, VideoArtifacts, derive_readiness_stage
from backend.schemas.video_jobs import JobPhase, JobStatus
from backend.services.library_changes import LibraryChangeNotifier
from backend.storage.postgres import (
    LibraryViewRow,
    PostgresLibraryViews,
    PostgresUserVideos,
    PostgresVideoJobs,
    StoredUser,
)

router = APIRouter(prefix="/v1/library")

# How long an idle progress stream stays silent before it sends an SSE comment, so a proxy
# does not close a connection that is only waiting for the next job.
PROGRESS_KEEPALIVE_SECONDS = 15.0
# How long a woken stream waits before reading, so a burst of download-progress writes
# becomes one read and one event instead of one per write.
PROGRESS_COALESCE_SECONDS = 0.3
ACTIVE_JOB_STATUSES = {"queued", "running", "awaiting_browser_download"}


def library_views(request: Request) -> PostgresLibraryViews:
    return request.app.state.library_views_store


def user_videos(request: Request) -> PostgresUserVideos:
    return request.app.state.user_videos_store


def video_jobs(request: Request) -> PostgresVideoJobs:
    return request.app.state.video_jobs_store


def library_changes(request: Request) -> LibraryChangeNotifier:
    return request.app.state.library_changes


def library_query(
    search: str | None = Query(default=None, max_length=256),
    tags: list[str] | None = Query(default=None),
    source_site: str | None = Query(default=None, max_length=256),
    stage: ReadinessStage | None = Query(default=None),
    added_after: str | None = Query(default=None),
    added_before: str | None = Query(default=None),
    has_conversations: bool | None = Query(default=None),
    sort: LibrarySort = Query(default=LibrarySort.ADDED_AT),
    direction: SortDirection = Query(default=SortDirection.DESCENDING),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LibraryQuery:
    """Parse the complete library query contract, including repeated tag parameters."""
    return LibraryQuery(
        search=search,
        tags=tags or [],
        source_site=source_site,
        stage=stage,
        added_after=added_after,
        added_before=added_before,
        has_conversations=has_conversations,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )


def _stage(row: LibraryViewRow):
    return derive_readiness_stage(
        VideoArtifacts(
            has_video_row=row.has_video_row,
            has_transcript=row.has_transcript,
            has_chapters=row.has_chapters,
            has_embeddings=row.has_embeddings,
            has_insights=row.has_insights,
        ),
        job_status=JobStatus(row.job_status) if row.job_status else None,
        job_phase=JobPhase(row.job_phase) if row.job_phase else None,
        job_error_code=row.error_code,
    )


def _library_video(row: LibraryViewRow) -> LibraryVideo:
    return LibraryVideo(
        video_id=row.video_id,
        job_id=row.job_id,
        title=row.custom_title or display_title(row.original_title, row.source_url, row.added_at),
        custom_title=row.custom_title,
        source_site=(urlsplit(row.source_url).hostname or ""),
        source=row.source or "",
        source_url=row.source_url,
        duration_seconds=row.duration_seconds,
        thumbnail_url=(f"/v1/videos/{row.video_id}/thumbnail" if row.video_id else None),
        tags=row.tags,
        added_at=row.added_at,
        stage=_stage(row),
        progress=row.progress,
        status_message=row.status_message,
        error_code=row.error_code,
        conversation_count=row.conversation_count,
    )


def _require_uuid(value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from error


@router.get("", response_model=LibraryPage)
def list_library(
    query: LibraryQuery = Depends(library_query),
    user: StoredUser = Depends(current_user),
    store: PostgresLibraryViews = Depends(library_views),
) -> LibraryPage:
    rows, total = store.list_page(
        user.id,
        search=query.search,
        tags=query.tags,
        source_site=query.source_site,
        stage=query.stage.value if query.stage else None,
        added_after=query.added_after,
        added_before=query.added_before,
        has_conversations=query.has_conversations,
        sort=query.sort.value,
        direction=query.direction.value,
        limit=query.limit,
        offset=query.offset,
    )
    return LibraryPage(
        videos=[_library_video(row) for row in rows],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.get("/tags", response_model=TagList)
def list_tags(
    user: StoredUser = Depends(current_user),
    store: PostgresUserVideos = Depends(user_videos),
) -> TagList:
    return TagList(tags=store.tags_for_user(user.id))


@router.get("/events")
async def library_events(
    user: StoredUser = Depends(current_user),
    store: PostgresLibraryViews = Depends(library_views),
    changes: LibraryChangeNotifier = Depends(library_changes),
) -> StreamingResponse:
    return StreamingResponse(
        library_progress_stream(user.id, store, changes),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def library_progress_stream(
    user_id: str,
    store: PostgresLibraryViews,
    changes: LibraryChangeNotifier,
    *,
    keepalive_seconds: float = PROGRESS_KEEPALIVE_SECONDS,
    coalesce_seconds: float = PROGRESS_COALESCE_SECONDS,
) -> AsyncIterator[str]:
    """Every job row's state once, then each row again whenever it changes, until closed.

    The stream stays open while nothing is processing, which is what lets the website
    see a job the extension starts later. It does not poll: it reads the database when
    the job manager reports a write for this user, and otherwise only sends a keepalive.
    While a job is active it also re-reads on each keepalive, as a safety net for a
    change made somewhere that does not notify.
    """
    previous: dict[str, str] = {}
    with changes.subscribe(user_id) as wake:
        while True:
            # Cleared before the read, so a write landing during it wakes the next wait.
            wake.clear()
            rows = await run_in_threadpool(store.progress_rows, user_id)
            for serialized in _changed_progress_events(rows, previous):
                yield f"data: {serialized}\n\n"
            active = any(row.job_status in ACTIVE_JOB_STATUSES for row in rows)
            while True:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=keepalive_seconds)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    if active:
                        break
                    continue
                await asyncio.sleep(coalesce_seconds)
                break


def _changed_progress_events(rows: list[LibraryViewRow], previous: dict[str, str]) -> list[str]:
    """The serialized event of each row that differs from what this stream last sent."""
    changed = []
    for row in rows:
        event = LibraryProgressEvent(
            job_id=row.job_id or "",
            video_id=row.video_id,
            stage=_stage(row),
            progress=row.progress,
            status_message=row.status_message,
            error_code=row.error_code,
        )
        serialized = event.model_dump_json()
        if previous.get(event.job_id) != serialized:
            previous[event.job_id] = serialized
            changed.append(serialized)
    return changed


@router.patch("/{video_id}", response_model=LibraryVideo)
def update_library_link(
    video_id: str,
    payload: UpdateLibraryLinkRequest,
    user: StoredUser = Depends(current_user),
    links: PostgresUserVideos = Depends(user_videos),
    views: PostgresLibraryViews = Depends(library_views),
) -> LibraryVideo:
    _require_uuid(video_id)
    if links.get(user.id, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    if "custom_title" in payload.model_fields_set:
        links.rename(user.id, video_id, payload.custom_title)
    if "tags" in payload.model_fields_set:
        links.set_tags(user.id, video_id, payload.tags or [])
    row = views.get_video(user.id, video_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return _library_video(row)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_library_video(
    video_id: str,
    user: StoredUser = Depends(current_user),
    links: PostgresUserVideos = Depends(user_videos),
) -> None:
    _require_uuid(video_id)
    if links.get(user.id, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    links.unlink(user.id, video_id)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_failed_library_job(
    job_id: str,
    user: StoredUser = Depends(current_user),
    jobs: PostgresVideoJobs = Depends(video_jobs),
) -> None:
    """Remove a job that ended without a video, the only trace of a failed upload."""
    if not jobs.delete_finished_without_video(job_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
