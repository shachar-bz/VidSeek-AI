"""A Pydantic AI tool that looks up the current video's metadata."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.core.errors import VideoNotFoundError
from backend.core.page_titles import clean_page_title
from backend.storage.postgres import PostgresVideoRecords

from ..deps import ConversationDeps


class VideoMetadata(BaseModel):
    """The video details relevant to a conversation about it."""

    source_url: str
    title: str
    transcript_source: str | None
    transcript_language: str | None


def get_video_info(ctx: RunContext[ConversationDeps]) -> VideoMetadata:
    """Look up the current video's metadata.

    Call this whenever you need the video's source URL, title, or transcript
    details and don't already have them.

    Returns:
        The video's metadata.

    Raises:
        VideoNotFoundError: No video exists with the current video id.
    """
    stored = PostgresVideoRecords(ctx.deps.pool).get_by_id(ctx.deps.video_id)
    if stored is None:
        raise VideoNotFoundError(ctx.deps.video_id)
    return VideoMetadata(
        source_url=stored.video.source_url,
        title=clean_page_title(stored.video.title, stored.video.source_url),
        transcript_source=stored.video.transcript_source,
        transcript_language=stored.video.transcript_language,
    )
