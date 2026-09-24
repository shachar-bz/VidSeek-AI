"""Public interface of the read_frame_text tool."""

from .result import FrameText, FrameTexts
from .tool import MAX_TIMESTAMPS_PER_CALL, covering_keyframe, read_frame_text

__all__ = ["MAX_TIMESTAMPS_PER_CALL", "FrameText", "FrameTexts", "covering_keyframe", "read_frame_text"]
