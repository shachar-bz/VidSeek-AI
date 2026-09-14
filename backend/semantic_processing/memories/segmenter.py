"""Divides a normalized transcript into semantic memories with `gpt-5.6-sol`.

This is the stage that runs after transcription. It hands the model the transcript with a
numbered ID on every line, asks only where one idea ends and the next begins, and builds
the memories itself from the original segments. The division is validated before anything
is built from it, so a model that skips a segment or invents an ID fails loudly here rather
than producing memories that quietly point at the wrong part of the video.

Needs `OPENAI_API_KEY_DUDU` in `backend/.env`.
"""

import logging
from collections.abc import Sequence

from openai import OpenAI

from backend.core import config
from backend.services.transcripts import NormalizedTranscript

from .boundaries import MemoryBoundary, TranscriptMemoryBoundaries
from .memory import VideoMemories, VideoMemory
from .prompt import memory_segmentation_prompt
from .segment_ids import SegmentIndex
from .validation import MemorySegmentationError, validate_boundaries

MODEL = "gpt-5.6-sol"

API_KEY_NAME = "OPENAI_API_KEY_DUDU"

# The SDK retries 429s and 5xx itself with exponential backoff, so the only thing left to
# choose here is how many times.
DEFAULT_MAX_RETRIES = 5

logger = logging.getLogger(__name__)


def build_client(max_retries: int = DEFAULT_MAX_RETRIES) -> OpenAI:
    """Build an OpenAI client authenticated with this project's key."""
    return OpenAI(api_key=config.require(API_KEY_NAME), max_retries=max_retries)


def segment_transcript(
    transcript: NormalizedTranscript,
    *,
    client: OpenAI | None = None,
    model: str = MODEL,
) -> VideoMemories:
    """Divide `transcript` into semantic memories, in one request.

    Raises `MemorySegmentationError` if the transcript is empty, if the model answers with
    nothing usable, or if the division it returns does not cover the transcript exactly
    once from beginning to end.
    """
    index = SegmentIndex(transcript.segments)
    if not index:
        raise MemorySegmentationError("The transcript has no segments to divide.")

    boundaries = request_boundaries(index, client=client, model=model)
    validate_boundaries(boundaries, index)

    logger.info(
        "Divided %d transcript segments into %d memories with %s",
        len(index),
        len(boundaries),
        model,
    )
    return VideoMemories(
        source=transcript.source,
        model=model,
        memories=build_memories(boundaries, index),
    )


def request_boundaries(
    index: SegmentIndex,
    *,
    client: OpenAI | None = None,
    model: str = MODEL,
) -> list[MemoryBoundary]:
    """Ask the model where each memory starts and ends, and return what it answered.

    Nothing about the answer is trusted yet: it is the right *shape*, because Structured
    Outputs enforced the schema, and that is all this function establishes.
    """
    client = client or build_client()
    response = client.responses.parse(
        model=model,
        instructions=memory_segmentation_prompt(),
        input=index.render(),
        text_format=TranscriptMemoryBoundaries,
    )

    parsed = response.output_parsed
    if parsed is None:
        raise MemorySegmentationError(
            f"{model} returned no parsed memories for this transcript; "
            f"the response finished as {getattr(response, 'status', 'unknown')}."
        )
    return parsed.memories


def build_memories(
    boundaries: Sequence[MemoryBoundary], index: SegmentIndex
) -> list[VideoMemory]:
    """Build each memory from the original transcript segments its IDs bound.

    Only `summary` comes from the model. The times and the text are read off the segments
    the transcription stage produced, which is what keeps them out of the model's reach.
    Call `validate_boundaries` first: this assumes the IDs resolve and the order holds.
    """
    return [
        VideoMemory(
            index=position,
            start_segment_id=boundary.start_segment_id,
            end_segment_id=boundary.end_segment_id,
            summary=boundary.summary,
            segments=index.between(boundary.start_segment_id, boundary.end_segment_id),
        )
        for position, boundary in enumerate(boundaries)
    ]
