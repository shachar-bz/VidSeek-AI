"""Public interface of the view_sequence tool."""

from .result import SequenceFrame, SequenceScene, ViewedSequence
from .tool import (
    DEFAULT_FRAME_COUNT,
    MAX_FRAME_COUNT,
    MIN_FRAME_COUNT,
    WINDOW_WITHOUT_SEGMENTS_SECONDS,
    view_sequence,
)

__all__ = [
    "DEFAULT_FRAME_COUNT",
    "MAX_FRAME_COUNT",
    "MIN_FRAME_COUNT",
    "WINDOW_WITHOUT_SEGMENTS_SECONDS",
    "SequenceFrame",
    "SequenceScene",
    "ViewedSequence",
    "view_sequence",
]
