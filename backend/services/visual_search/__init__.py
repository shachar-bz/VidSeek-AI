"""Public interface of the visual search service: moments of one video that match a text query."""

from .fusion import FusedItem, reciprocal_rank_fusion
from .scoring import HitRange, StandoutFrame, merge_into_ranges, standout_frames
from .search import (
    DEFAULT_SETTINGS,
    IMAGE,
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    INDEX_READY,
    OCR_MEANING,
    OCR_WORDS,
    TRANSCRIPT,
    SearchSettings,
    TimeRange,
    VisualMoment,
    VisualSearchResult,
    search_visual_moments,
)
from .video_map import VideoVisualMap, load_video_map

__all__ = [
    "DEFAULT_SETTINGS",
    "IMAGE",
    "INDEX_NOT_READY",
    "INDEX_OUTDATED",
    "INDEX_READY",
    "OCR_MEANING",
    "OCR_WORDS",
    "TRANSCRIPT",
    "FusedItem",
    "HitRange",
    "SearchSettings",
    "StandoutFrame",
    "TimeRange",
    "VideoVisualMap",
    "VisualMoment",
    "VisualSearchResult",
    "load_video_map",
    "merge_into_ranges",
    "reciprocal_rank_fusion",
    "search_visual_moments",
    "standout_frames",
]
