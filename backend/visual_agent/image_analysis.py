"""The image model that looks at frames for the visual sub-agent and reports what they show.

The sub-agent's own model plans the investigation and never receives an image. When it needs to
know what frames show, `view_frames` hands them here with the question, and a vision model
(`IMAGE_MODEL_NAME`) answers in text. Keeping pixels out of the planner's context keeps its
history small and lets the planner and the eye be priced and chosen separately.

Each frame is sent after a label naming its position and time, and the model answers with one
observation per frame, in the same order, plus an answer to the question across all of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.core import config
from backend.services.video_frames import ExtractedFrame, format_timestamp

from .prompt import IMAGE_ANALYSIS_PROMPT

# The same key every other OpenAI call site in the backend reads (see `video_agent/runner.py`).
API_KEY_NAME = "OPENAI_API_KEY_DUDU"
IMAGE_MODEL_NAME = "gpt-6-luna"


class FrameAnalysis(BaseModel):
    """What the image model saw in a set of frames."""

    frames: list[str] = Field(
        description=(
            "One observation per frame, in the order the frames were given: what the frame "
            "shows that bears on the question."
        )
    )
    answer: str = Field(
        description=(
            "The answer to the question across all the frames. Says so when the frames do not "
            "show it, or show it unclearly."
        )
    )


class ImageAnalyzer(Protocol):
    """Looks at frames and says what they show, in answer to a question."""

    async def analyze(self, question: str, frames: Sequence[ExtractedFrame]) -> FrameAnalysis: ...


class OpenAIImageAnalyzer:
    """Frames and a question sent to OpenAI's vision model, one request per call."""

    def __init__(self, model: str = IMAGE_MODEL_NAME):
        self._agent: Agent[None, FrameAnalysis] = Agent(
            # The Responses API rather than Chat Completions: gpt-6-luna refuses function tools
            # (which carry the structured answer) on Chat Completions while it reasons.
            OpenAIResponsesModel(model, provider=OpenAIProvider(api_key=config.require(API_KEY_NAME))),
            output_type=FrameAnalysis,
            instructions=IMAGE_ANALYSIS_PROMPT,
            defer_model_check=True,
        )

    async def analyze(self, question: str, frames: Sequence[ExtractedFrame]) -> FrameAnalysis:
        result = await self._agent.run(frame_prompt(question, frames))
        return result.output


def frame_prompt(question: str, frames: Sequence[ExtractedFrame]) -> list[str | BinaryContent]:
    """The question, then each frame after a label giving its position and time."""
    content: list[str | BinaryContent] = [f"Question: {question}\nThere are {len(frames)} frames."]
    for position, frame in enumerate(frames, start=1):
        content.append(f"Frame {position}, at {format_timestamp(frame.time_seconds)}:")
        content.append(BinaryContent(data=frame.image_bytes, media_type=frame.media_type))
    return content
