"""Public interface of the visual search service: searches over one video's visual index.

`search_visual_moments` finds frames whose picture looks like what a query describes;
`search_screen_text` finds on-screen text by what it means and by exact words. None of them
needs an agent to run. `search_visual_text` is the exact-word search alone, for the visual
sub-agent until it is removed.
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
from .text_search import MAX_MOMENTS, MAX_WORDS, normalized, search_screen_text, search_visual_text
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
    "search_visual_text",
    "standout_frames",
    "standout_positions",
    "z_scores",
]
