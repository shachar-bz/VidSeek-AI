"""Public interface of the visual indexing service: one video's index, built from its local file.

`CURRENT_VISUAL_INDEX_VERSION` is the label every index built now carries, and the one search
accepts. It changes whenever the image model or the sampling rate does.
"""

from .indexer import (
    BuiltVisualIndex,
    IndexedFrame,
    NoFramesToIndex,
    build_visual_index,
    visual_index_version,
)
from .sampling import SAMPLE_INTERVAL_SECONDS, FrameSamplingError, SamplingStopped

# Spelled out rather than imported from `embeddings.image_embedding`, which would load torch
# and transformers for every importer of this package; `test_visual_indexing` checks that the
# two stay the same.
IMAGE_MODEL_NAME = "google/siglip2-base-patch16-256"

CURRENT_VISUAL_INDEX_VERSION = visual_index_version(IMAGE_MODEL_NAME, SAMPLE_INTERVAL_SECONDS)

__all__ = [
    "CURRENT_VISUAL_INDEX_VERSION",
    "IMAGE_MODEL_NAME",
    "SAMPLE_INTERVAL_SECONDS",
    "BuiltVisualIndex",
    "FrameSamplingError",
    "IndexedFrame",
    "NoFramesToIndex",
    "SamplingStopped",
    "build_visual_index",
    "visual_index_version",
]
