"""Everything that has to happen to one video, in order, from a URL to a searchable video.

This package is the pipeline and nothing else. The work belongs to the services — the
downloaders, the transcription and forced-alignment services, the semantic segmentation
stages, the embedding pipelines, the stores — and every one of them existed before this
package did. What was missing was the order they run in, the handover between them, and the
decision about which failures are worth losing a video over. That is what lives here.

    acquisition  -> video_storage -> segmentation -> embedding
    download +      Blob Storage +   memories +      memory and
    transcript      videos row       chapters        chapter vectors

`run_download_pipeline` runs all four. Each stage is also importable on its own, which is
what makes a video that failed at stage three or four recoverable: neither of those stages
needs anything the process that downloaded the video still holds, only its `videos` row.
"""

from .acquisition import AcquisitionRoute, acquire_video
from .embedding import EmbeddedVideo, embed_video
from .pipeline import run_download_pipeline
from .result import (
    CHAPTER_GROUPING_FAILED,
    EMBEDDING_FAILED,
    RECORD_FAILED,
    SEGMENTATION_FAILED,
    ProcessedVideo,
    VideoStorageError,
)
from .segmentation import SegmentedVideo, segment_and_store
from .video_storage import StorageOutcome, store_video

__all__ = [
    "CHAPTER_GROUPING_FAILED",
    "EMBEDDING_FAILED",
    "RECORD_FAILED",
    "SEGMENTATION_FAILED",
    "AcquisitionRoute",
    "EmbeddedVideo",
    "ProcessedVideo",
    "SegmentedVideo",
    "StorageOutcome",
    "VideoStorageError",
    "acquire_video",
    "embed_video",
    "run_download_pipeline",
    "segment_and_store",
    "store_video",
]
