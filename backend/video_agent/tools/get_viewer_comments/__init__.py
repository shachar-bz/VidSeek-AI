"""Public interface of the get_viewer_comments tool."""

from .result import ViewerComment, ViewerComments
from .tool import (
    MAX_COMMENTS,
    MAX_TEXT_CHARS,
    MIN_SIMILARITY,
    get_viewer_comments,
    only_for_a_video_with_comments,
    viewer_comments_tool,
)

__all__ = [
    "MAX_COMMENTS",
    "MAX_TEXT_CHARS",
    "MIN_SIMILARITY",
    "ViewerComment",
    "ViewerComments",
    "get_viewer_comments",
    "only_for_a_video_with_comments",
    "viewer_comments_tool",
]
