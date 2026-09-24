"""Public interface of the video frames service: frames of a stored video, extracted on demand.

Used only at query time. Indexing reads the local file while it exists and never comes here.
"""

from .extraction import (
    FRAME_LONG_SIDE,
    ExtractedFrame,
    FrameExtractionError,
    extract_frame,
    extract_frames,
)
from .grid import build_frame_grid, evenly_spaced_times, format_timestamp
from .source import FRAME_LINK_LIFETIME_SECONDS, VideoFrameSource, VideoNotStoredError

__all__ = [
    "FRAME_LINK_LIFETIME_SECONDS",
    "FRAME_LONG_SIDE",
    "ExtractedFrame",
    "FrameExtractionError",
    "VideoFrameSource",
    "VideoNotStoredError",
    "build_frame_grid",
    "evenly_spaced_times",
    "extract_frame",
    "extract_frames",
    "format_timestamp",
]
