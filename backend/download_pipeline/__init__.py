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

A sixth stage branches off after `video_storage` rather than following `insights`:

    video_storage -> visual_indexing (on the job manager's visual executor, in parallel)
                     frame vectors, segments, keyframes, then the keyframes' on-screen text

`hand_over_for_visual_indexing` is called by the pipeline; `index_video_visually` is the
background task the job manager runs, and the one stage that needs the local video file.
`reindex_video_visually` is the same task for an index a shutdown interrupted, run from the
stored video once the job manager starts again.
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
from .visual_indexing import (
    ScheduleVisualIndexing,
    VisualIndexingOutcome,
    claim_interrupted_visual_indexing,
    hand_over_for_visual_indexing,
    index_video_visually,
    mark_visual_indexing_never_run,
    reindex_video_visually,
)

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
    "ScheduleVisualIndexing",
    "SegmentedVideo",
    "StorageOutcome",
    "VideoStorageError",
    "VisualIndexingOutcome",
    "acquire_video",
    "claim_interrupted_visual_indexing",
    "embed_video",
    "generate_and_store_insights",
    "hand_over_for_visual_indexing",
    "index_video_visually",
    "mark_visual_indexing_never_run",
    "reindex_video_visually",
    "run_download_pipeline",
    "segment_and_store",
    "store_video",
]
