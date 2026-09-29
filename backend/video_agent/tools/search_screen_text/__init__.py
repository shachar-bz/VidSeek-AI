"""Public interface of the search_screen_text tool."""

from .result import ScreenTextMoment, ScreenTextMoments
from .tool import search_screen_text

__all__ = ["ScreenTextMoment", "ScreenTextMoments", "search_screen_text"]
