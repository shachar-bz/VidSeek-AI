"""Public interface of the view_frames_closeup tool."""

from .result import CloseupFrame, CloseupFrames
from .tool import CLOSEUP_LONG_SIDE, MAX_FRAMES_PER_CALL, view_frames_closeup

__all__ = [
    "CLOSEUP_LONG_SIDE",
    "MAX_FRAMES_PER_CALL",
    "CloseupFrame",
    "CloseupFrames",
    "view_frames_closeup",
]
