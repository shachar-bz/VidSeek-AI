"""Public interface of the visual search service: two searches over one video's visual index.

`search_visual_moments` finds what a query describes, by the picture and by what on-screen text
means; `search_visual_text` finds given words written on screen. Neither needs an agent to run.
"""

from .moment_search import DEFAULT_SETTINGS, MomentSearchSettings, join_lists, search_visual_moments
from .moments import (
    IMAGE,
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    INDEX_READY,
    ON_SCREEN_TEXT_CHARACTERS,
    TEXT_CHARACTERS,
    TEXT_MEANING,
    TRANSCRIPT_CHARACTERS,
    TimeWindow,
    VisualMoment,
    VisualSearchResult,
    ready_video_map,
)
from .scoring import (
    HitRange,
    StandoutFrame,
    merge_into_ranges,
    standout_frames,
    standout_positions,
    z_scores,
)
from .text_search import MAX_MOMENTS, MAX_WORDS, normalized, search_visual_text
from .video_map import VideoVisualMap, load_video_map

__all__ = [
    "DEFAULT_SETTINGS",
    "IMAGE",
    "INDEX_NOT_READY",
    "INDEX_OUTDATED",
    "INDEX_READY",
    "MAX_MOMENTS",
    "MAX_WORDS",
    "ON_SCREEN_TEXT_CHARACTERS",
    "TEXT_CHARACTERS",
    "TEXT_MEANING",
    "TRANSCRIPT_CHARACTERS",
    "HitRange",
    "MomentSearchSettings",
    "StandoutFrame",
    "TimeWindow",
    "VideoVisualMap",
    "VisualMoment",
    "VisualSearchResult",
    "join_lists",
    "load_video_map",
    "merge_into_ranges",
    "normalized",
    "ready_video_map",
    "search_visual_moments",
    "search_visual_text",
    "standout_frames",
    "standout_positions",
    "z_scores",
]
