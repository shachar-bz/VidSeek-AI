"""Public interface of the view_frames_closeup tool."""

from .result import ViewedFrame, ViewedFrames
from .tool import CLOSEUP_LONG_SIDE, MAX_FRAMES_PER_CALL, view_frames_closeup

__all__ = [
    "CLOSEUP_LONG_SIDE",
    "MAX_FRAMES_PER_CALL",
    "ViewedFrame",
    "ViewedFrames",
    "view_frames_closeup",
]
