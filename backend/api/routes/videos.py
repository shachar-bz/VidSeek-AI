"""Authenticated video metadata, playback, transcript, outline, and pin HTTP endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.dependencies import current_user
from backend.api.routes.library import _require_uuid, _stage, library_views
from backend.schemas.videos import (
    PLAYBACK_URL_LIFETIME_SECONDS,
    ChapterOutlineEntry,
    PinAnswerRequest,
    PinnedAnswer,
    PinnedAnswerList,
    PlaybackUrl,
    TranscriptLine,
    VideoDetail,
    VideoInsights,
    VideoOutlineResponse,
    VideoTranscript,
)
from backend.storage.blob.video_storage import BlobVideoStorage
from backend.storage.postgres import (
    PostgresChapters,
    PostgresLibraryViews,
    PostgresPinnedAnswers,
    PostgresTranscriptSegments,
    StoredUser,
)

router = APIRouter(prefix="/v1/videos")


def transcripts(request: Request) -> PostgresTranscriptSegments:
    return getattr(request.app.state, "transcript_segments_store", PostgresTranscriptSegments())


def chapters(request: Request) -> PostgresChapters:
    return getattr(request.app.state, "chapters_store", PostgresChapters())


def pins(request: Request) -> PostgresPinnedAnswers:
    return getattr(request.app.state, "pinned_answers_store", PostgresPinnedAnswers())


def blob_storage(request: Request) -> BlobVideoStorage:
    stored = getattr(request.app.state, "blob_video_storage", None)
    return stored if stored is not None else BlobVideoStorage()


def _owned_video(user_id: str, video_id: str, store: PostgresLibraryViews):
    _require_uuid(video_id)
    row = store.get_video(user_id, video_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return row


def _pin_response(pin) -> PinnedAnswer:
    return PinnedAnswer(
        pin_id=pin.id,
        message_id=pin.message_id,
        conversation_id=pin.conversation_id,
        content=pin.content,
        pinned_at=pin.pinned_at,
    )


@router.get("/{video_id}", response_model=VideoDetail)
def video_detail(
    video_id: str,
    user: StoredUser = Depends(current_user),
    store: PostgresLibraryViews = Depends(library_views),
) -> VideoDetail:
    row = _owned_video(user.id, video_id, store)
    stage = _stage(row)
    insights = None
    if stage.allows_chat and row.insights_summary is not None:
        insights = VideoInsights(
            summary=row.insights_summary,
            takeaways=row.insights_takeaways or [],
            suggested_questions=row.insights_suggested_questions or [],
        )
    return VideoDetail(
        video_id=video_id,
        title=row.custom_title or row.original_title,
        custom_title=row.custom_title,
        original_title=row.original_title,
        source_site=urlsplit(row.source_url).hostname or "",
        source_url=row.source_url,
        duration_seconds=row.duration_seconds,
        tags=row.tags,
        added_at=row.added_at or "",
        stage=stage,
        transcript_source=row.transcript_source,
        transcript_language=row.transcript_language,
        transcript_timing_fidelity=row.transcript_timing_fidelity,
        insights=insights,
        conversation_count=row.conversation_count,
    )


@router.get("/{video_id}/playback", response_model=PlaybackUrl)
def playback_url(
    video_id: str,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    storage: BlobVideoStorage = Depends(blob_storage),
) -> PlaybackUrl:
    row = _owned_video(user.id, video_id, views)
    if not row.blob_name or not storage.video_exists(row.blob_name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video file not found")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=PLAYBACK_URL_LIFETIME_SECONDS)
    return PlaybackUrl(
        url=storage.sas_download_url(row.blob_name, PLAYBACK_URL_LIFETIME_SECONDS),
        expires_at=expires_at.isoformat(),
        expires_in_seconds=PLAYBACK_URL_LIFETIME_SECONDS,
    )


@router.get("/{video_id}/transcript", response_model=VideoTranscript)
def video_transcript(
    video_id: str,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    store: PostgresTranscriptSegments = Depends(transcripts),
) -> VideoTranscript:
    row = _owned_video(user.id, video_id, views)
    return VideoTranscript(
        video_id=video_id,
        timing_fidelity=row.transcript_timing_fidelity,
        lines=[
            TranscriptLine(
                index=item.index,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                text=item.text,
            )
            for item in store.load(video_id)
        ],
    )


@router.get("/{video_id}/outline", response_model=VideoOutlineResponse)
def video_outline(
    video_id: str,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    store: PostgresChapters = Depends(chapters),
) -> VideoOutlineResponse:
    _owned_video(user.id, video_id, views)
    return VideoOutlineResponse(
        video_id=video_id,
        chapters=[ChapterOutlineEntry(**vars(item)) for item in store.video_outline(video_id)],
    )


@router.get("/{video_id}/pins", response_model=PinnedAnswerList)
def list_pins(
    video_id: str,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    store: PostgresPinnedAnswers = Depends(pins),
) -> PinnedAnswerList:
    _owned_video(user.id, video_id, views)
    return PinnedAnswerList(
        video_id=video_id,
        pins=[_pin_response(item) for item in store.list_for_video(user.id, video_id)],
    )


@router.post("/{video_id}/pins", response_model=PinnedAnswer)
def pin_answer(
    video_id: str,
    payload: PinAnswerRequest,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    store: PostgresPinnedAnswers = Depends(pins),
) -> PinnedAnswer:
    _owned_video(user.id, video_id, views)
    try:
        uuid.UUID(payload.message_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found") from error
    pinned = store.pin_for_video(user.id, video_id, payload.message_id)
    if pinned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return _pin_response(pinned)


@router.delete("/{video_id}/pins/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def unpin_answer(
    video_id: str,
    message_id: str,
    user: StoredUser = Depends(current_user),
    views: PostgresLibraryViews = Depends(library_views),
    store: PostgresPinnedAnswers = Depends(pins),
) -> None:
    _owned_video(user.id, video_id, views)
    try:
        uuid.UUID(message_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found") from error
    if not store.unpin_for_video(user.id, video_id, message_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found")
