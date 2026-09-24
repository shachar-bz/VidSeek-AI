"""The image model that looks at frames for the visual sub-agent and reports what they show.

The sub-agent's own model plans the investigation and never receives an image. When it needs to
know what frames show, `view_frames` hands them here with the question, and a vision model
(`IMAGE_MODEL_NAME`) answers in text. Keeping pixels out of the planner's context keeps its
history small and lets the planner and the eye be priced and chosen separately.

Each frame is sent after a label naming its position and time, and the model answers with one
observation per frame, in the same order, plus an answer to the question across all of them.

`view_sequence` sends a sequence instead: one grid image of frames across a window, after a list
of each cell's time and scene, under its own instructions (`SEQUENCE_ANALYSIS_PROMPT`), which
ask what changes from cell to cell. The answer has the same shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.core import config
from backend.services.video_frames import JPEG, ExtractedFrame, format_timestamp

from .prompt import IMAGE_ANALYSIS_PROMPT, SEQUENCE_ANALYSIS_PROMPT

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


@dataclass(frozen=True)
class SequenceCell:
    """One cell of a sequence grid: when its frame is shown, and which scene of the window it is in."""

    time_seconds: float
    # The scene's number within the window, from 1; None when the video's scenes are not known.
    scene: int | None = None


class ImageAnalyzer(Protocol):
    """Looks at frames and says what they show, in answer to a question."""

    async def analyze(self, question: str, frames: Sequence[ExtractedFrame]) -> FrameAnalysis: ...

    async def analyze_sequence(
        self, question: str, grid_jpeg: bytes, cells: Sequence[SequenceCell]
    ) -> FrameAnalysis: ...


class OpenAIImageAnalyzer:
    """Frames and a question sent to OpenAI's vision model, one request per call."""

    def __init__(self, model: str = IMAGE_MODEL_NAME):
        # The Responses API rather than Chat Completions: gpt-6-luna refuses function tools
        # (which carry the structured answer) on Chat Completions while it reasons.
        vision_model = OpenAIResponsesModel(
            model, provider=OpenAIProvider(api_key=config.require(API_KEY_NAME))
        )
        self._frames_agent: Agent[None, FrameAnalysis] = Agent(
            vision_model,
            output_type=FrameAnalysis,
            instructions=IMAGE_ANALYSIS_PROMPT,
            defer_model_check=True,
        )
        self._sequence_agent: Agent[None, FrameAnalysis] = Agent(
            vision_model,
            output_type=FrameAnalysis,
            instructions=SEQUENCE_ANALYSIS_PROMPT,
            defer_model_check=True,
        )

    async def analyze(self, question: str, frames: Sequence[ExtractedFrame]) -> FrameAnalysis:
        result = await self._frames_agent.run(frame_prompt(question, frames))
        return result.output

    async def analyze_sequence(
        self, question: str, grid_jpeg: bytes, cells: Sequence[SequenceCell]
    ) -> FrameAnalysis:
        result = await self._sequence_agent.run(sequence_prompt(question, grid_jpeg, cells))
        return result.output


def frame_prompt(question: str, frames: Sequence[ExtractedFrame]) -> list[str | BinaryContent]:
    """The question, then each frame after a label giving its position and time."""
    content: list[str | BinaryContent] = [f"Question: {question}\nThere are {len(frames)} frames."]
    for position, frame in enumerate(frames, start=1):
        content.append(f"Frame {position}, at {format_timestamp(frame.time_seconds)}:")
        content.append(BinaryContent(data=frame.image_bytes, media_type=frame.media_type))
    return content


def sequence_prompt(
    question: str, grid_jpeg: bytes, cells: Sequence[SequenceCell]
) -> list[str | BinaryContent]:
    """The question, each cell's time and scene, where the cuts fall, then the grid."""
    listed = ", ".join(
        f"Frame {position} at {format_timestamp(cell.time_seconds)}"
        + (f" (scene {cell.scene})" if cell.scene is not None else "")
        for position, cell in enumerate(cells, start=1)
    )
    lines = [
        f"Question: {question}",
        f"The image is a grid of {len(cells)} frames from {format_timestamp(cells[0].time_seconds)} "
        f"to {format_timestamp(cells[-1].time_seconds)}, in time order, read left to right, then "
        f"top to bottom: {listed}.",
    ]
    cuts = [
        f"between frame {position} and frame {position + 1}"
        for position, (before, after) in enumerate(zip(cells, cells[1:]), start=1)
        if before.scene != after.scene
    ]
    if cuts:
        lines.append(f"There is a cut {', and '.join(cuts)}.")
    elif cells[0].scene is None:
        lines.append("Where the video cuts from scene to scene is not known.")
    return ["\n".join(lines), BinaryContent(data=grid_jpeg, media_type=JPEG)]
