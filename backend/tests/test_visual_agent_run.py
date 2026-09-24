"""End-to-end runs of the visual sub-agent against a scripted model, and the main agent's investigate_visual.

The sub-agent is the one `build_visual_agent` builds -- its tools, its instructions, its
findings check -- with pydantic_ai's `FunctionModel` put in place of OpenAI, so each test
scripts the planner's turns and nothing leaves the machine. Frames, the image model and every
store are the same kind of stand-ins the tool tests use.
"""

import asyncio

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.services.video_frames import JPEG, ExtractedFrame
from backend.tests.fake_postgres import FakePool
from backend.video_agent import citations
from backend.video_agent import runner as main_runner
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.investigate_visual import tool as investigate_visual_tool
from backend.video_agent.tools.investigate_visual import investigate_visual
from backend.visual_agent import runner
from backend.visual_agent.budget import BUDGET_SPENT, MAX_TOOL_CALLS, USAGE_LIMITS
from backend.visual_agent.image_analysis import FrameAnalysis
from backend.visual_agent.result import VisualFinding, VisualInvestigation
from backend.visual_agent.tools.deps import VisualDeps

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CURRENT_TIME = 130.0
QUESTION = "What is on the whiteboard?"


class FakeFrameSource:
    def __init__(self):
        self.calls: list[list[float]] = []

    def frames(self, video_id, times, *, long_side=512, lossless=False):
        self.calls.append(list(times))
        return [ExtractedFrame(time_seconds=t, image_bytes=b"jpeg-bytes", media_type=JPEG) for t in times]


class FakeImageAnalyzer:
    async def analyze(self, question, frames):
        return FrameAnalysis(
            frames=["A whiteboard with three boxes labelled P0, P1, P2." for _ in frames],
            answer="Three partitions drawn as boxes.",
        )


class FakeRunContext:
    """The single attribute investigate_visual reads off a RunContext."""

    def __init__(self, deps: ConversationDeps):
        self.deps = deps


def _deps(frame_source: FakeFrameSource | None = None) -> VisualDeps:
    return VisualDeps(
        video_id=VIDEO_ID,
        current_time_seconds=CURRENT_TIME,
        pool=FakePool(rows=[]),
        frame_source=frame_source or FakeFrameSource(),
        image_analyzer=FakeImageAnalyzer(),
        ocr_engine=lambda: None,
    )


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def _retry_prompts(messages: list[ModelMessage]) -> list[RetryPromptPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]


def _final_answer(info: AgentInfo, answer: str, *spans: tuple[float, float]) -> ModelResponse:
    """The planner's answer, sent the way pydantic_ai asks for structured output: its output tool."""
    findings = [
        {
            "start_seconds": start,
            "end_seconds": end,
            "observation": "Three boxes labelled P0, P1, P2.",
            "evidence": "image",
        }
        for start, end in spans
    ]
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, {"answer": answer, "findings": findings})]
    )


def _look_at_the_current_frame() -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart("view_frames", {"timestamps": [CURRENT_TIME], "question": QUESTION})]
    )


@pytest.fixture
def visual_agent(monkeypatch: pytest.MonkeyPatch):
    """The production sub-agent, built with a key that is never used because no request is sent."""
    monkeypatch.setenv(runner.API_KEY_NAME, "test-key-never-sent")
    return runner.build_visual_agent()


def _investigate(agent, model_function, deps: VisualDeps, **range_seconds) -> VisualInvestigation:
    async def run():
        with agent.override(model=FunctionModel(model_function)):
            return await runner.run_investigation(
                QUESTION, video_id=VIDEO_ID, agent=agent, deps=deps, **range_seconds
            )

    return asyncio.run(run())


# --- the sub-agent, end to end ----------------------------------------------------------


def test_the_sub_agent_refuses_to_build_without_the_project_api_key(monkeypatch) -> None:
    monkeypatch.delenv(runner.API_KEY_NAME, raising=False)

    with pytest.raises(RuntimeError, match=runner.API_KEY_NAME):
        runner.build_visual_agent()


def test_the_planner_gets_its_tools_its_instructions_and_the_viewer_s_position(visual_agent) -> None:
    seen: dict = {}

    def model(messages, info: AgentInfo):
        seen["tools"] = sorted(tool.name for tool in info.function_tools)
        seen["instructions"] = info.instructions
        seen["prompt"] = messages[0].parts[-1].content
        return _final_answer(info, "Nothing was looked at.")

    _investigate(visual_agent, model, _deps(), start_seconds=120.0, end_seconds=None)

    assert seen["tools"] == [
        "get_transcript_window",
        "read_frame_text",
        "search_visual_moments",
        "search_visual_text",
        "view_frames",
        "view_sequence",
    ]
    assert "You investigate what is shown in one video" in seen["instructions"]
    assert f"Question: {QUESTION}" in seen["prompt"]
    assert "02:10" in seen["prompt"]
    assert "from 02:00 (120.0 s) to the end" in seen["prompt"]


def test_a_finding_at_a_frame_the_planner_looked_at_is_accepted(visual_agent) -> None:
    source = FakeFrameSource()
    deps = _deps(source)

    def model(messages, info: AgentInfo):
        returns = _tool_returns(messages)
        if not returns:
            return _look_at_the_current_frame()
        # The image model's words reached the planner, never the frame itself.
        assert "P0, P1, P2" in returns[0].model_response_str()
        return _final_answer(info, "Three partitions, drawn as boxes.", (CURRENT_TIME, CURRENT_TIME))

    result = _investigate(visual_agent, model, deps)

    assert result.answer == "Three partitions, drawn as boxes."
    assert [(finding.start_seconds, finding.end_seconds) for finding in result.findings] == [
        (CURRENT_TIME, CURRENT_TIME)
    ]
    assert source.calls == [[CURRENT_TIME]]
    assert deps.spans == [(CURRENT_TIME, CURRENT_TIME)]
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 1)


def test_an_invented_moment_sent_back_once_and_corrected_is_accepted(visual_agent) -> None:
    def model(messages, info: AgentInfo):
        if not _tool_returns(messages):
            return _look_at_the_current_frame()
        if not _retry_prompts(messages):
            return _final_answer(info, "Three partitions.", (600.0, 600.0))
        return _final_answer(info, "Three partitions.", (CURRENT_TIME, CURRENT_TIME))

    result = _investigate(visual_agent, model, _deps())

    assert [(finding.start_seconds, finding.end_seconds) for finding in result.findings] == [
        (CURRENT_TIME, CURRENT_TIME)
    ]


def test_an_invented_moment_given_twice_is_dropped_and_the_answer_kept(visual_agent) -> None:
    requests: list[list[ModelMessage]] = []

    def model(messages, info: AgentInfo):
        requests.append(list(messages))
        return _final_answer(info, "Probably a diagram of partitions.", (600.0, 605.0))

    result = _investigate(visual_agent, model, _deps())

    assert result.answer == "Probably a diagram of partitions."
    assert result.findings == []
    # Asked once, sent back once naming the moment, then accepted without the finding.
    assert len(requests) == 1 + runner.FINDINGS_RETRIES
    (retry,) = _retry_prompts(requests[-1])
    assert "10:00-10:05" in retry.model_response()


def test_a_planner_that_never_stops_calling_tools_gets_the_out_of_budget_answer(visual_agent) -> None:
    requests: list[list[ModelMessage]] = []

    def model(messages, info: AgentInfo):
        requests.append(list(messages))
        return ModelResponse(
            parts=[ToolCallPart("get_transcript_window", {"start_seconds": 0.0, "end_seconds": 10.0})]
        )

    deps = _deps()
    result = _investigate(visual_agent, model, deps)

    assert result == VisualInvestigation(answer=runner.OUT_OF_BUDGET_ANSWER, findings=[])
    returns = _tool_returns(requests[-1])
    # The soft cap answered every call past it with "budget spent" before the hard stop.
    assert len(returns) == USAGE_LIMITS.tool_calls_limit
    assert all(BUDGET_SPENT in part.model_response_str() for part in returns[MAX_TOOL_CALLS:])
    assert "That was your last tool call" in returns[MAX_TOOL_CALLS - 1].model_response_str()
    assert deps.budget.tool_calls_used == MAX_TOOL_CALLS


# --- investigate_visual, the main agent's tool ------------------------------------------


def _capture_investigations(monkeypatch, answer: VisualInvestigation | Exception) -> list[dict]:
    calls: list[dict] = []

    async def fake_run_investigation(question, **arguments):
        calls.append({"question": question, **arguments})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(investigate_visual_tool, "run_investigation", fake_run_investigation)
    return calls


def test_the_viewer_s_position_comes_from_the_deps_and_the_range_is_passed_through(monkeypatch) -> None:
    answer = VisualInvestigation(answer="Three partitions.")
    calls = _capture_investigations(monkeypatch, answer)
    pool = FakePool()
    deps = ConversationDeps(video_id=VIDEO_ID, current_time_seconds=CURRENT_TIME, pool=pool)

    result = asyncio.run(
        investigate_visual(FakeRunContext(deps), QUESTION, start_seconds=120.0, end_seconds=180.0)
    )

    assert result is answer
    assert calls == [
        {
            "question": QUESTION,
            "video_id": VIDEO_ID,
            "current_time_seconds": CURRENT_TIME,
            "start_seconds": 120.0,
            "end_seconds": 180.0,
            "pool": pool,
        }
    ]


def test_with_no_range_given_none_is_passed(monkeypatch) -> None:
    calls = _capture_investigations(monkeypatch, VisualInvestigation(answer="x"))
    deps = ConversationDeps(video_id=VIDEO_ID)

    asyncio.run(investigate_visual(FakeRunContext(deps), QUESTION))

    assert (calls[0]["current_time_seconds"], calls[0]["start_seconds"], calls[0]["end_seconds"]) == (
        None,
        None,
        None,
    )


def test_a_failed_investigation_answers_that_it_failed_instead_of_raising(monkeypatch) -> None:
    _capture_investigations(monkeypatch, RuntimeError("OpenAI is down"))
    deps = ConversationDeps(video_id=VIDEO_ID, current_time_seconds=CURRENT_TIME)

    result = asyncio.run(investigate_visual(FakeRunContext(deps), QUESTION))

    assert result == VisualInvestigation(answer=investigate_visual_tool.FAILED_ANSWER, findings=[])


def test_the_findings_are_moments_the_main_agent_may_cite() -> None:
    result = VisualInvestigation(
        answer="Three partitions.",
        findings=[
            VisualFinding(start_seconds=130.0, end_seconds=130.0, observation="Boxes.", evidence="image"),
            VisualFinding(start_seconds=200.0, end_seconds=210.5, observation="Said.", evidence="transcript"),
        ],
    )

    assert citations.spans_of(result) == [(130.0, 130.0), (200.0, 210.5)]
    draft = citations.AnswerDraft()
    draft.record(result)
    assert citations.unverified("The board shows three partitions. [02:10] [03:20–03:30]", draft.spans) == []
    assert main_runner._summarize_result(result) == "2 findings"


def test_the_main_agent_carries_investigate_visual_and_is_told_about_it() -> None:
    assert investigate_visual in main_runner.TOOLS
    assert "investigate_visual" in main_runner.SYSTEM_PROMPT
