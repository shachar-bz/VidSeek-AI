"""Public interface of the search_video_speech tool."""

from .result import MemorySearchHit, MemorySearchResult
from .tool import search_video_speech

__all__ = ["MemorySearchHit", "MemorySearchResult", "search_video_speech"]
