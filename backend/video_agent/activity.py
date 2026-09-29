"""What each tool is doing, in words, for the line a client shows under a pending answer.

One generic label per tool, written here so that the website and the extension say the same
thing while an answer is being generated. A label is for display while waiting and nothing
else: it travels on the live stream and is never stored with the trace.
"""

from __future__ import annotations

TOOL_ACTIVITY: dict[str, str] = {
    "get_video_info": "Checking the video's details",
    "get_video_outline": "Reading the outline",
    "get_chapter_context": "Reading a chapter",
    "get_memory_context": "Reading a moment closely",
    "memories_semantic_search": "Searching the video",
    "get_viewer_comments": "Reading viewer comments",
    "investigate_visual": "Looking at what the video shows",
}


def tool_activity(tool: str) -> str | None:
    """The label for a tool call, or None for a tool without one."""

    return TOOL_ACTIVITY.get(tool)
