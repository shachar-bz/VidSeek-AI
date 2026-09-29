"""The five visual tools as the agent is offered them: only for a video whose picture can be looked at.

Each tool's `prepare` takes it out of the model's schema unless the video's visual index is
ready, the way `get_viewer_comments` is offered only for a video with comments: a video still
being indexed, or one that never will be, has nothing to search and nothing the tools could
trust, and the prompt's visual section tells the agent what to say instead.
"""

from __future__ import annotations

from pydantic_ai import RunContext, Tool
from pydantic_ai.tools import ToolDefinition

from backend.services.visual_search import VISUAL_READY

from .deps import ConversationDeps
from .search_screen_text import search_screen_text
from .search_visual_moments import search_visual_moments
from .view_candidates import view_candidates
from .view_frames_closeup import view_frames_closeup
from .view_sequence import view_sequence


async def only_when_the_picture_can_be_looked_at(
    ctx: RunContext[ConversationDeps], tool_definition: ToolDefinition
) -> ToolDefinition | None:
    """Offer the tool only when the video's visual index is ready."""
    return tool_definition if ctx.deps.visual_availability == VISUAL_READY else None


VISUAL_TOOLS = tuple(
    Tool(tool, prepare=only_when_the_picture_can_be_looked_at)
    for tool in (
        search_visual_moments,
        search_screen_text,
        view_candidates,
        view_sequence,
        view_frames_closeup,
    )
)
