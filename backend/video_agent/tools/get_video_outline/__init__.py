"""Public interface of the get_video_outline tool."""

from .result import ChapterOutline, VideoOutline
from .tool import get_video_outline

__all__ = ["ChapterOutline", "VideoOutline", "get_video_outline"]
