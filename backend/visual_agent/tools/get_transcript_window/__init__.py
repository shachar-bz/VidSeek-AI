"""Public interface of the get_transcript_window tool."""

from .result import TranscriptPiece, TranscriptWindow
from .tool import MAX_WINDOW_SECONDS, get_transcript_window

__all__ = ["MAX_WINDOW_SECONDS", "TranscriptPiece", "TranscriptWindow", "get_transcript_window"]
