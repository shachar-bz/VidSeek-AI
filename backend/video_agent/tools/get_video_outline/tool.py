"""A Pydantic AI tool that reads the structure of the current video."""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.core.errors import VideoNotFoundError
from backend.storage.postgres import PostgresChapters, PostgresVideoRecords

from ..deps import ConversationDeps
from .result import ChapterOutline, VideoOutline


def get_video_outline(ctx: RunContext[ConversationDeps]) -> VideoOutline:
    """Show the structure of this video as an ordered outline of its chapters, each with
    its title, summary, and start and end times.

    Use it to understand how the video is organized, to locate where a topic or activity
    appears, or to identify its sections.

    Returns:
        The video's chapters in chronological order. Returns an empty list if no chapters
        are available.

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
