"""Authenticated library listing, metadata edits, unlinking, tags, and progress events."""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from backend.api.dependencies import current_user
from backend.core.page_titles import clean_page_title
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
from backend.storage.postgres import (
    LibraryViewRow,
    PostgresLibraryViews,
    PostgresUserVideos,
    StoredUser,
)

router = APIRouter(prefix="/v1/library")


def library_views(request: Request) -> PostgresLibraryViews:
    return request.app.state.library_views_store


def user_videos(request: Request) -> PostgresUserVideos:
    return request.app.state.user_videos_store


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
            has_timed_transcript=row.has_timed_transcript,
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
        title=row.custom_title or clean_page_title(row.original_title, row.source_url),
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
) -> StreamingResponse:
    async def events():
        previous: dict[str, str] = {}
        while True:
            rows = store.progress_rows(user.id)
            active = False
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
                    yield f"data: {serialized}\n\n"
                if row.job_status in {"queued", "running", "awaiting_browser_download"}:
                    active = True
            if not active:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
