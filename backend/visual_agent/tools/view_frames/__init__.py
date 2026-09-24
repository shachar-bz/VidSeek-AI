"""Public interface of the view_frames tool."""

from .result import ViewedFrame, ViewedFrames
from .tool import MAX_FRAMES_PER_CALL, view_frames

__all__ = ["MAX_FRAMES_PER_CALL", "ViewedFrame", "ViewedFrames", "view_frames"]
