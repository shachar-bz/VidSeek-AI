"""Public interface of the frame sampling module."""

from .frame_stream import (
    SAMPLE_INTERVAL_SECONDS,
    SAMPLE_LONG_SIDE,
    FrameSamplingError,
    SampledFrame,
    SamplingStopped,
    sample_frames,
)
from .keyframes import KEYFRAME_LONG_SIDE, decode_frame_at

__all__ = [
    "KEYFRAME_LONG_SIDE",
    "SAMPLE_INTERVAL_SECONDS",
    "SAMPLE_LONG_SIDE",
    "FrameSamplingError",
    "SampledFrame",
    "SamplingStopped",
    "decode_frame_at",
    "sample_frames",
]
