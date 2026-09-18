"""A Pydantic AI tool that reads the structure of the current video."""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.core.errors import VideoNotFoundError
from backend.storage.postgres import PostgresChapters, PostgresVideoRecords

from ..deps import ConversationDeps
from .result import ChapterOutline, VideoOutline


def get_video_outline(ctx: RunContext[ConversationDeps]) -> VideoOutline:
    """Read this video's chapters in order.

    Each chapter comes back with its title, summary and timing, and nothing of what was
    said in it. A chapter's id is what `get_chapter_context` reads to open that chapter in
    full.

    Returns:
        Every chapter of the video, earliest first. Empty when this video has not been
        divided into chapters.

    Raises:
        VideoNotFoundError: No video exists with the current video id.
    """
    chapters = PostgresChapters(ctx.deps.pool).video_outline(ctx.deps.video_id)
    # Only an empty outline is ambiguous: a video with chapters has proved it exists, and
    # asking the `videos` table to confirm it again would be a second round trip spent on
    # a question already answered. An empty outline is a video that was never divided into
    # chapters or an id that describes nothing, and only here are the two worth separating.
    if not chapters and not PostgresVideoRecords(ctx.deps.pool).exists(ctx.deps.video_id):
        raise VideoNotFoundError(ctx.deps.video_id)
    return VideoOutline(
        chapters=[
            ChapterOutline(
                chapter_id=chapter.chapter_id,
                chapter_index=chapter.chapter_index,
                title=chapter.title,
                summary=chapter.summary,
                start_seconds=chapter.start_seconds,
                end_seconds=chapter.end_seconds,
            )
            for chapter in chapters
        ]
    )
