"""Public interface of the frame sampling module."""

from .frame_stream import (
    SAMPLE_INTERVAL_SECONDS,
    SAMPLE_LONG_SIDE,
    FrameSamplingError,
    SampledFrame,
    SamplingStopped,
    sample_frames,
)

__all__ = [
    "SAMPLE_INTERVAL_SECONDS",
    "SAMPLE_LONG_SIDE",
    "FrameSamplingError",
    "SampledFrame",
    "SamplingStopped",
    "sample_frames",
]
