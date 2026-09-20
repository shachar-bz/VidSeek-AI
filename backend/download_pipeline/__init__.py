"""Everything that turns one captured video into durable, searchable generated artifacts.

This package is the pipeline and nothing else. The work belongs to the services — the
downloaders, the transcription and forced-alignment services, the semantic segmentation
stages, the embedding pipelines and the stores. This package owns the order they run in,
the handover between them, and the decision about which failures are worth losing a video
over.

    acquisition -> video_storage -> segmentation -> embedding -> insights
    download +     Blob Storage +   memories +      memory and    summary,
    transcript     videos row       chapters        chapter       takeaways,
                                                   vectors       questions

`run_download_pipeline` runs all five. Each stage is also importable on its own, which is
what makes later-stage failures recoverable: those stages need only durable video artifacts,
not anything held by the process that downloaded the video.
"""

from .acquisition import AcquisitionRoute, acquire_video
from .embedding import EmbeddedVideo, embed_video
from .insights import InsightGenerationOutcome, generate_and_store_insights
from .pipeline import run_download_pipeline
from .result import (
    CHAPTER_GROUPING_FAILED,
    EMBEDDING_FAILED,
    INSIGHT_GENERATION_FAILED,
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
    "INSIGHT_GENERATION_FAILED",
    "RECORD_FAILED",
    "SEGMENTATION_FAILED",
    "AcquisitionRoute",
    "EmbeddedVideo",
    "InsightGenerationOutcome",
    "ProcessedVideo",
    "SegmentedVideo",
    "StorageOutcome",
    "VideoStorageError",
    "acquire_video",
    "embed_video",
    "generate_and_store_insights",
    "run_download_pipeline",
    "segment_and_store",
    "store_video",
]
