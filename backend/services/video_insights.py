"""Generate a video's summary, takeaways and starter questions from stored summaries."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.core import config

MODEL = "gpt-6-luna"
API_KEY_NAME = "OPENAI_API_KEY_DUDU"
DEFAULT_MAX_RETRIES = 5

logger = logging.getLogger(__name__)


class InsightGenerationError(ValueError):
    """The supplied artifacts or model response cannot produce usable insights."""


@dataclass(frozen=True)
class InsightChapter:
    """One chapter reduced to the generated summaries the insights model may read."""

    title: str
    summary: str
    memory_summaries: tuple[str, ...]


class GeneratedVideoInsights(BaseModel):
    """The validated structured output stored for one video."""

    summary: str = Field(min_length=1)
    takeaways: list[str] = Field(min_length=1, max_length=5)
    suggested_questions: list[str] = Field(min_length=1, max_length=3)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        """Reject an answer whose summary is only whitespace."""
        value = value.strip()
        if not value:
            raise ValueError("summary must not be blank")
        return value

    @field_validator("takeaways", "suggested_questions")
    @classmethod
    def validate_items(cls, values: list[str]) -> list[str]:
        """Trim list items and reject blank takeaways or questions."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("items must not be blank")
        return cleaned


def build_client(max_retries: int = DEFAULT_MAX_RETRIES) -> OpenAI:
    """Build an OpenAI client authenticated with this project's key."""
    return OpenAI(api_key=config.require(API_KEY_NAME), max_retries=max_retries)


def generate_video_insights(
    chapters: Sequence[InsightChapter],
    *,
    client: OpenAI | None = None,
    model: str = MODEL,
) -> GeneratedVideoInsights:
    """Generate and validate insights from chapter and memory summaries only."""
    if not chapters:
        raise InsightGenerationError("The video has no chapters to summarize.")

    client = client or build_client()
    response = client.responses.parse(
        model=model,
        instructions=video_insights_prompt(),
        input=render_chapter_summaries(chapters),
        text_format=GeneratedVideoInsights,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise InsightGenerationError(
            f"{model} returned no parsed insights; "
            f"the response finished as {getattr(response, 'status', 'unknown')}."
        )

    try:
        # Validate again at the service boundary. The SDK normally returns this Pydantic
        # type already, but callers and tests may supply an object built without validation.
        validated = GeneratedVideoInsights.model_validate(parsed.model_dump())
    except (AttributeError, ValidationError) as error:
        raise InsightGenerationError(f"{model} returned invalid video insights.") from error

    logger.info("Generated insights from %d chapters with %s", len(chapters), model)
    return validated


def render_chapter_summaries(chapters: Sequence[InsightChapter]) -> str:
    """Render only generated chapter and memory summaries as the model input."""
    rendered: list[str] = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        rendered.append(f"Chapter {chapter_index}: {chapter.title}\n{chapter.summary}")
        rendered.extend(
            f"- Memory {memory_index}: {summary}"
            for memory_index, summary in enumerate(chapter.memory_summaries, start=1)
        )
    return "\n\n".join(rendered)


def video_insights_prompt() -> str:
    """
    You are given the ordered chapter summaries and memory summaries from one video.

    Generate an overall summary of the video, up to five key takeaways, and up to three
    suggested questions a viewer could ask to explore the video's content.

    Base every insight only on the supplied video artifacts. Keep the summary concise, make
    each takeaway distinct and useful, and make each suggested question specific to the video.
    """
    return inspect.cleandoc(video_insights_prompt.__doc__)
