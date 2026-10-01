"""Tests for the video agent's view_frames_closeup tool: frames returned to the agent itself, as images.

Most tests call the tool directly with a real ConversationDeps, a frame source handing back small
real JPEGs, and the chapter outline from a `FakePool`. One runs it through the real runner with
pydantic_ai's `FunctionModel` in place of OpenAI, to check what reaches the model after the call
and what the citation check is left holding.
"""

import asyncio
import json

import pytest
from pydantic_ai import Agent, BinaryContent, ToolReturn
from pydantic_ai.messages import ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from backend.services.video_frames import JPEG, FrameExtractionError, VideoNotStoredError
from backend.tests.fake_postgres import FakePool
from backend.tests.fake_visual_looks import VIDEO_ID, FakeFrameSource, FakeRunContext, look_deps
from backend.video_agent import runner
from backend.video_agent.citations import spans_of
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.view_frames_closeup import (
    CLOSEUP_LONG_SIDE,
    CloseupFrames,
    view_frames_closeup,
)
from backend.video_agent.tools.visual_budget_spent import VisualBudgetSpent
from backend.video_agent.visual_budget import MAX_LOOKS, MAX_VISUAL_TOOL_CALLS

CHAPTERS = [
    {"chapter_id": "c0", "chapter_index": 0, "title": "Introduction", "summary": "", "start_seconds": 0.0, "end_seconds": 120.0},
    {"chapter_id": "c1", "chapter_index": 1, "title": "Kafka partitions", "summary": "", "start_seconds": 120.0, "end_seconds": 600.0},
]


def _deps(*, frame_source: FakeFrameSource | None = None) -> ConversationDeps:
    return look_deps(FakePool(rows=CHAPTERS), frame_source=frame_source)


def _view(deps: ConversationDeps, times: list[float]):
    return asyncio.run(view_frames_closeup(FakeRunContext(deps), times))


# --- the frames, as images ------------------------------------------------------------------


def test_the_frames_come_back_as_labelled_images_for_one_call_and_one_look() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [130.0, 131.5])

    assert isinstance(result, ToolReturn)
    listed = result.return_value
    assert isinstance(listed, CloseupFrames)
    assert [(f.frame, f.time_seconds, f.timestamp, f.chapter) for f in listed.frames] == [
        (1, 130.0, "02:10", "Kafka partitions"),
        (2, 131.5, "02:11", "Kafka partitions"),
    ]
    assert listed.note is None
    assert listed.budget == f"{MAX_VISUAL_TOOL_CALLS - 1} visual tool calls and {MAX_LOOKS - 1} looks left."
    # Each image follows its label, in the order asked for.
    labels, images = result.content[0::2], result.content[1::2]
    assert labels == ["Frame 1 at 02:10", "Frame 2 at 02:11"]
    assert all(isinstance(image, BinaryContent) and image.media_type == JPEG for image in images)
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 1)
    # Large JPEGs of this video.
    assert CLOSEUP_LONG_SIDE == 1024
    assert source.calls == [{"video_id": VIDEO_ID, "times": [130.0, 131.5], "long_side": CLOSEUP_LONG_SIDE}]


def test_every_frame_shown_is_citable_as_an_instant() -> None:
    result = _view(_deps(), [130.0, 131.5])

    assert spans_of(result.return_value) == [(130.0, 130.0), (131.5, 131.5)]


def test_repeated_and_negative_times_are_shown_once_from_the_start() -> None:
    source = FakeFrameSource()

    _view(_deps(frame_source=source), [-4.0, 0.0, 10.0, 10.0])

    assert source.calls[0]["times"] == [0.0, 10.0]


def test_more_than_three_times_are_cut_to_the_first_three_and_says_so() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [float(second) for second in range(5)])

    assert source.calls[0]["times"] == [0.0, 1.0, 2.0]
    assert len(result.return_value.frames) == 3
    assert result.return_value.note == "Only the first 3 times were looked at."
    assert deps.visual_budget.looks_used == 1


# --- calls that show nothing ----------------------------------------------------------------


def test_no_times_shows_nothing_and_spends_nothing() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [])

    assert isinstance(result, CloseupFrames)
    assert result.note == "Nothing was looked at, and no tool call was spent: no times were given."
    assert source.calls == []
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (0, 0)


@pytest.mark.parametrize(
    "failure",
    [FrameExtractionError("The video has no frame at 900.0 s"), VideoNotStoredError("no stored file")],
)
def test_frames_that_cannot_be_extracted_give_their_look_back(failure: Exception) -> None:
    deps = _deps(frame_source=FakeFrameSource(failure))

    result = _view(deps, [900.0, 901.0])

    assert isinstance(result, CloseupFrames)
    assert result.frames == []
    assert result.note == f"The frames could not be extracted: {failure}"
    assert (deps.visual_budget.tool_calls_used, deps.visual_budget.looks_used) == (1, 0)
    assert spans_of(result) == []


def test_with_no_looks_left_nothing_is_extracted() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_LOOKS):
        deps.visual_budget.take_look()

    result = _view(deps, [10.0])

    assert isinstance(result, CloseupFrames)
    assert result.note == "No looks are left in this answer's budget."
    assert source.calls == []


def test_after_six_visual_calls_view_frames_closeup_does_no_work_and_says_the_budget_is_spent() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    for _ in range(MAX_VISUAL_TOOL_CALLS):
        deps.visual_budget.start_tool_call()

    assert isinstance(_view(deps, [10.0]), VisualBudgetSpent)
    assert source.calls == []


# --- through the runner ---------------------------------------------------------------------


def test_through_the_runner_the_model_receives_the_images_and_the_frame_times_become_citable() -> None:
    received: list = []

    # The runner streams, so the stand-in model streams too: first the close view, then an answer.
    async def stream_function(messages, info: AgentInfo):
        last = messages[-1]
        if not any(isinstance(part, ToolReturnPart) for part in last.parts):
            yield {0: DeltaToolCall(name="view_frames_closeup", json_args=json.dumps({"times": [130.0, 131.5]}))}
            return
        received.extend(part for part in last.parts if isinstance(part, UserPromptPart))
        yield "The whiteboard shows a partition diagram [02:10]."

    agent = Agent(
        FunctionModel(stream_function=stream_function),
        deps_type=ConversationDeps,
        output_type=str,
        tools=[view_frames_closeup],
    )
    deps = _deps()

    async def collect():
        return [
            event
            async for event in runner.PydanticConversationAgentRunner(agent).stream(
                "What is on the whiteboard?", history=[], deps=deps
            )
        ]

    events = asyncio.run(collect())

    # The images reach the model in the request right after the tool's result, each after its label.
    [follow_up] = received
    assert [item for item in follow_up.content if isinstance(item, str)] == ["Frame 1 at 02:10", "Frame 2 at 02:11"]
    assert sum(isinstance(item, BinaryContent) for item in follow_up.content) == 2
    # The citation filter holds the frames' times, so the answer citing one passes unchanged.
    assert deps.retrieved.spans == [(130.0, 130.0), (131.5, 131.5)]
    assert "".join(event.text for event in events if isinstance(event, runner.TextFragment)) == "The whiteboard shows a partition diagram [02:10]."
