"""The third stage of the pipeline: a video's memories grouped into semantic chapters.

Memory segmentation leaves a video as a few dozen coherent ideas, which is the right shape
for answering a question about a specific moment and the wrong shape for asking what a
video is about, or for finding the stretch where it argues something. This package groups
consecutive memories into chapters: the broader sections a video divides into, each holding
several related memories on one topic, theme, argument or stage of the discussion.

The model sees only the memory summaries, never the transcript — the previous stage already
decided what each memory says, and the judgment left here is which of those belong together.
It decides only where one chapter ends and the next begins, by naming the memory IDs that
bound it. Every timestamp a chapter then claims is read back out of the original memories,
and the grouping is validated to cover them exactly once before any of it is built. The
model's contribution to the finished result is each chapter's title and summary.
"""

from .boundaries import ChapterBoundary, VideoChapterBoundaries
from .chapter import VideoChapter, VideoChapters
from .grouper import MODEL, build_chapters, build_client, group_memories, request_boundaries
from .memory_ids import MEMORY_ID_PREFIX, MemoryIndex, UnknownMemoryIdError, format_memory_id
from .prompt import chapter_grouping_prompt
from .validation import ChapterGroupingError, validate_boundaries

__all__ = [
    "MEMORY_ID_PREFIX",
    "MODEL",
    "ChapterBoundary",
    "ChapterGroupingError",
    "MemoryIndex",
    "UnknownMemoryIdError",
    "VideoChapter",
    "VideoChapterBoundaries",
    "VideoChapters",
    "build_chapters",
    "build_client",
    "chapter_grouping_prompt",
    "format_memory_id",
    "group_memories",
    "request_boundaries",
    "validate_boundaries",
]
