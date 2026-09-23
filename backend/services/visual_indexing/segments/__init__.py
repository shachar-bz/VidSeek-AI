"""Public interface of the content-change segmentation module."""

from .perceptual_hash import hash_distance, perceptual_hash
from .segmenter import (
    DEFAULT_SETTINGS,
    SCENE_CHANGE,
    TEXT_CHANGE,
    VIDEO_START,
    FrameSignature,
    SegmentationSettings,
    VisualSegment,
    divide_into_segments,
)

__all__ = [
    "DEFAULT_SETTINGS",
    "SCENE_CHANGE",
    "TEXT_CHANGE",
    "VIDEO_START",
    "FrameSignature",
    "SegmentationSettings",
    "VisualSegment",
    "divide_into_segments",
    "hash_distance",
    "perceptual_hash",
]
