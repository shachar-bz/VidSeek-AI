"""Public interface of the visual search service: searches over one video's visual index.

`search_visual_moments` finds frames whose picture looks like what a query describes;
`search_screen_text` finds on-screen text by what it means and by exact words. None of them
needs an agent to run. `visual_availability` says whether a video's picture can be searched and
looked at yet.
"""

from .moment_search import DEFAULT_SETTINGS, MomentSearchSettings, search_visual_moments
from .moments import (
    IMAGE,
    INDEX_NOT_READY,
    INDEX_OUTDATED,
    INDEX_READY,
    ON_SCREEN_TEXT_CHARACTERS,
    TEXT_CHARACTERS,
    TEXT_MEANING,
    VISUAL_PROCESSING,
    VISUAL_READY,
    VISUAL_UNAVAILABLE,
    VisualMoment,
    VisualSearchResult,
    ready_video_map,
    visual_availability,
)
from .scoring import (
    HitRange,
    StandoutFrame,
    merge_into_ranges,
    standout_frames,
    standout_positions,
    z_scores,
)
from .text_search import MAX_MOMENTS, MAX_WORDS, normalized, search_screen_text
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
    "VISUAL_PROCESSING",
    "VISUAL_READY",
    "VISUAL_UNAVAILABLE",
    "HitRange",
    "MomentSearchSettings",
    "StandoutFrame",
    "VideoVisualMap",
    "VisualMoment",
    "VisualSearchResult",
    "load_video_map",
    "merge_into_ranges",
    "normalized",
    "ready_video_map",
    "search_screen_text",
    "search_visual_moments",
    "standout_frames",
    "standout_positions",
    "visual_availability",
    "z_scores",
]
