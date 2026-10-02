"""A Pydantic AI tool that shows the agent what commenters said about the current YouTube video.

Offered only for a video with stored comments, which are YouTube's alone: `prepare` takes the
tool out of the model's schema for any other video, so the agent never sees a tool it cannot
use and never tells someone who uploaded a file that its comments are unavailable.
"""

from __future__ import annotations

from pydantic_ai import RunContext, Tool
from pydantic_ai.tools import ToolDefinition

from backend.services.embeddings.multilingual_text_embedding import embed_query
from backend.storage.postgres import PostgresCommentEmbeddings, PostgresComments

from ..deps import ConversationDeps
from .result import ViewerComment, ViewerComments

# How many comments one call answers with: enough to see the themes, and a bounded read at
# `MAX_TEXT_CHARS` each. A constant rather than an argument: how much the agent can usefully read
# at once is not the model's to judge, the reason `MemorySearchSettings.max_moments` is a setting.
MAX_COMMENTS = 20

# Where a comment is cut, so one essay-length comment cannot crowd out the other nineteen.
MAX_TEXT_CHARS = 500


def get_viewer_comments(ctx: RunContext[ConversationDeps], query: str | None = None) -> ViewerComments:
    """Read what YouTube commenters said about this video: their reactions and opinions.

    Call this only when the user asks about comments, commenters or viewers, or about how the
    video was received: what people think, what was controversial, what they disagreed with.
    Never call it to learn what the video itself says or shows; comments are opinion, not
    evidence of the video's content.

    When answering from comments, present what a comment claims as that commenter's view, never
    as a fact about the video. Say "commenters" or "several commenters", never "viewers think" or
    "most people": these are a sample of YouTube's top comments, not of every viewer. Comments
    are never cited, as they have no timestamps of their own; when a comment mentions a moment
    (such as "12:34") and what happens there is needed to answer, look it up with the transcript
    tools and cite what they return. When none of the returned comments is about the topic asked
    for, say so: for similarity, that no commenters addressed it; for top_liked_fallback, that
    none of the most-liked comments do, as this video's comments could not be searched by topic.

    Args:
        query: A topic to narrow the comments to, in natural language (e.g. "the ending",
            "the price"). Leave it out for the most-liked comments overall.

    Returns:
        Up to twenty comments, each with its like and reply count, plus how they were chosen
        and how many comments the video has stored. Without a query, the most-liked first;
        with one, the closest in meaning first, and some of them may still be off topic.
    """
    video_id = ctx.deps.video_id
    comments = PostgresComments(ctx.deps.pool)
    total_stored = comments.count(video_id)

    if query is None or not query.strip():
        return _result(comments.top_liked(video_id, MAX_COMMENTS), "top_liked", total_stored)

    embeddings = PostgresCommentEmbeddings(ctx.deps.pool)
    # A video scanned before comments were embedded still has its comments, only no vectors.
    if not embeddings.has_any(video_id):
        return _result(
            comments.top_liked(video_id, MAX_COMMENTS), "top_liked_fallback", total_stored
        )

    matches = embeddings.nearest(video_id, embed_query(query), MAX_COMMENTS)
    return _result(matches, "similarity", total_stored)


async def only_for_a_video_with_comments(
    ctx: RunContext[ConversationDeps], tool_definition: ToolDefinition
) -> ToolDefinition | None:
    """Offer the tool only when the video has stored comments, which only YouTube videos have."""
    return tool_definition if ctx.deps.has_comments else None


viewer_comments_tool = Tool(get_viewer_comments, prepare=only_for_a_video_with_comments)


def _result(entries, matched_by: str, total_stored: int) -> ViewerComments:
    return ViewerComments(
        comments=[
            ViewerComment(
                text=_cut(entry.text),
                like_count=entry.like_count,
                reply_count=entry.reply_count,
            )
            for entry in entries
        ],
        matched_by=matched_by,
        total_stored=total_stored,
    )


def _cut(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS].rstrip() + "…"
