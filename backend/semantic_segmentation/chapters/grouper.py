"""Groups a video's semantic memories into higher-level chapters with `gpt-5.6-sol`.

This is the stage that runs after memory segmentation. It hands the model the memories as
one line each — an ID, a timecode and the summary the previous stage wrote, and none of the
transcript — asks only where one broad topic ends and the next begins, and builds the
chapters itself from the original memories. The grouping is validated before anything is
built from it, so a model that skips a memory or invents an ID fails loudly here rather
than producing chapters that quietly point at the wrong part of the video.

Needs `OPENAI_API_KEY_DUDU` in `backend/.env`.
"""

import logging
from collections.abc import Sequence

from openai import OpenAI

from backend.core import config

from ..memories import VideoMemories
from .boundaries import ChapterBoundary, VideoChapterBoundaries
from .chapter import VideoChapter, VideoChapters
from .memory_ids import MemoryIndex
from .prompt import chapter_grouping_prompt
from .validation import ChapterGroupingError, validate_boundaries

MODEL = "gpt-5.6-sol"

API_KEY_NAME = "OPENAI_API_KEY_DUDU"

# The SDK retries 429s and 5xx itself with exponential backoff, so the only thing left to
# choose here is how many times.
DEFAULT_MAX_RETRIES = 5

logger = logging.getLogger(__name__)


def build_client(max_retries: int = DEFAULT_MAX_RETRIES) -> OpenAI:
    """Build an OpenAI client authenticated with this project's key."""
    return OpenAI(api_key=config.require(API_KEY_NAME), max_retries=max_retries)


def group_memories(
    memories: VideoMemories,
    *,
    client: OpenAI | None = None,
    model: str = MODEL,
) -> VideoChapters:
    """Group `memories` into semantic chapters, in one request.

    Raises `ChapterGroupingError` if there are no memories, if the model answers with
    nothing usable, or if the grouping it returns does not cover the memories exactly once
    from beginning to end.
    """
    index = MemoryIndex(memories.memories)
    if not index:
        raise ChapterGroupingError("The video has no memories to group.")

    boundaries = request_boundaries(index, client=client, model=model)
    validate_boundaries(boundaries, index)

    logger.info(
        "Grouped %d memories into %d chapters with %s",
        len(index),
        len(boundaries),
        model,
    )
    return VideoChapters(
        source=memories.source,
        model=model,
        chapters=build_chapters(boundaries, index),
    )


def request_boundaries(
    index: MemoryIndex,
    *,
    client: OpenAI | None = None,
    model: str = MODEL,
) -> list[ChapterBoundary]:
    """Ask the model where each chapter starts and ends, and return what it answered.

    Nothing about the answer is trusted yet: it is the right *shape*, because Structured
    Outputs enforced the schema, and that is all this function establishes.
    """
    client = client or build_client()
    response = client.responses.parse(
        model=model,
        instructions=chapter_grouping_prompt(),
        input=index.render(),
        text_format=VideoChapterBoundaries,
    )

    parsed = response.output_parsed
    if parsed is None:
        raise ChapterGroupingError(
            f"{model} returned no parsed chapters for these memories; "
            f"the response finished as {getattr(response, 'status', 'unknown')}."
        )
    return parsed.chapters


def build_chapters(
    boundaries: Sequence[ChapterBoundary], index: MemoryIndex
) -> list[VideoChapter]:
    """Build each chapter from the original memories its IDs bound.

    Only `title` and `summary` come from the model. The times are read off the memories the
    previous stage produced, which is what keeps them out of the model's reach. Call
    `validate_boundaries` first: this assumes the IDs resolve and the order holds.
    """
    return [
        VideoChapter(
            index=position,
            start_memory_id=boundary.start_memory_id,
            end_memory_id=boundary.end_memory_id,
            title=boundary.title,
            summary=boundary.summary,
            memories=index.between(boundary.start_memory_id, boundary.end_memory_id),
        )
        for position, boundary in enumerate(boundaries)
    ]
