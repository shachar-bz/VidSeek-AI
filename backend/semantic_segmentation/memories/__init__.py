"""The second stage of the pipeline: a transcript divided into semantic memories.

Transcription leaves a video as a long list of short timed segments, which is the right
shape for playback and the wrong shape for search — a segment is a line of speech, not an
idea, and an answer to a question about the video is almost never contained in one. This
package turns that list into memories: stretches of transcript that each hold a single
idea, story or argument, long enough to still make sense read on their own.

An LLM decides only where one memory ends and the next begins, by naming the segment IDs
that bound it. Everything a memory then claims — its start time, its end time, its
transcript — is read back out of the original segments, and the division is validated to
cover the transcript exactly once before any of it is built. The model's one contribution
to the finished result is each memory's summary.
"""

from .boundaries import MemoryBoundary, TranscriptMemoryBoundaries
from .memory import VideoMemories, VideoMemory
from .prompt import memory_segmentation_prompt
from .segment_ids import SEGMENT_ID_PREFIX, SegmentIndex, UnknownSegmentIdError, format_segment_id
from .segmenter import MODEL, build_client, build_memories, request_boundaries, segment_transcript
from .validation import MemorySegmentationError, validate_boundaries

__all__ = [
    "MODEL",
    "SEGMENT_ID_PREFIX",
    "MemoryBoundary",
    "MemorySegmentationError",
    "SegmentIndex",
    "TranscriptMemoryBoundaries",
    "UnknownSegmentIdError",
    "VideoMemories",
    "VideoMemory",
    "build_client",
    "build_memories",
    "format_segment_id",
    "memory_segmentation_prompt",
    "request_boundaries",
    "segment_transcript",
    "validate_boundaries",
]
