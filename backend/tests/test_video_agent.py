"""Tests the agent's fixed model, tool set, streamed citation check, and persisted-history conversion."""

import asyncio
import warnings
from pathlib import Path

import pytest
from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.messages import ModelResponse, TextPart, TextPartDelta, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.services.visual_search import VISUAL_PROCESSING, VISUAL_READY, VISUAL_UNAVAILABLE
from backend.storage.postgres import StoredMessage
from backend.video_agent import image_analysis, prompt, runner
from backend.video_agent.activity import tool_activity
from backend.video_agent.tools.deps import ConversationDeps

NOW = "2026-09-19T10:00:00+00:00"
RETRIEVED = [(730.0, 760.0)]


class FakeEventStream:
    """One agent run's events, optionally ending in a failure."""

    def __init__(self, events, failure=None):
        self._events = events
        self._failure = failure

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        async def replay():
            for event in self._events:
                yield event
            if self._failure is not None:
                raise self._failure

        return replay()


class FakeStreamingAgent:
    def __init__(self, events, failure=None):
        self._events = events
        self._failure = failure

    def run_stream_events(self, prompt, *, deps, message_history):
        return FakeEventStream(self._events, self._failure)


def _written(text: str):
    return [
        PartStartEvent(index=0, part=TextPart(content="")),
        PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=text)),
    ]


def _run(agent, deps) -> list:
    async def collect():
        return [
            event
            async for event in runner.PydanticConversationAgentRunner(agent).stream(
                "question", history=[], deps=deps
            )
        ]

    return asyncio.run(collect())


def test_agent_refuses_to_build_without_the_project_api_key(monkeypatch) -> None:
    monkeypatch.delenv(runner.API_KEY_NAME, raising=False)

    with pytest.raises(RuntimeError, match=runner.API_KEY_NAME):
        runner.build_agent()


def test_only_supplied_conversation_messages_become_model_history() -> None:
    history = [
        StoredMessage("u", "current", "user", "question", None, NOW),
        StoredMessage("a", "current", "assistant", "answer", None, NOW),
    ]

    converted = runner._model_history(history)

    assert len(converted) == 3
    assert converted[0].parts[0].content == runner.SYSTEM_PROMPT
    assert converted[1].parts[0].content == "question"
    assert converted[2].parts[0].content == "answer"


TRANSCRIPT_TOOLS = [
    "get_video_info",
    "get_video_outline",
    "memories_semantic_search",
    "get_chapter_context",
    "get_memory_context",
]
VISUAL_TOOLS = [
    "search_visual_moments",
    "search_screen_text",
    "view_candidates",
    "view_sequence",
    "view_frames_closeup",
]


def _offered_tools(deps: ConversationDeps) -> list[str]:
    """The tool names the model is offered on its first step, for a run with these deps."""
    offered: list[str] = []

    def answer(messages, info: AgentInfo) -> ModelResponse:
        offered.extend(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart(content="answer")])

    agent = Agent(FunctionModel(answer), deps_type=ConversationDeps, output_type=str, tools=list(runner.TOOLS))
    agent.run_sync("question", deps=deps)
    return offered


@pytest.mark.parametrize(
    ("availability", "has_comments", "expected"),
    [
        (VISUAL_READY, False, TRANSCRIPT_TOOLS + VISUAL_TOOLS),
        (VISUAL_READY, True, TRANSCRIPT_TOOLS + VISUAL_TOOLS + ["get_viewer_comments"]),
        (VISUAL_PROCESSING, False, TRANSCRIPT_TOOLS),
        (VISUAL_UNAVAILABLE, True, TRANSCRIPT_TOOLS + ["get_viewer_comments"]),
    ],
)
def test_the_visual_tools_are_offered_only_for_a_ready_visual_index(availability, has_comments, expected) -> None:
    deps = ConversationDeps(video_id="video", visual_availability=availability, has_comments=has_comments)

    assert _offered_tools(deps) == expected


def test_every_tool_has_an_activity_label_and_the_old_visual_tool_is_gone() -> None:
    for name in TRANSCRIPT_TOOLS + VISUAL_TOOLS + ["get_viewer_comments"]:
        assert tool_activity(name), name
    assert tool_activity("investigate_visual") is None
    assert "investigate_visual" not in runner.SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("availability", "section"),
    [
        (VISUAL_READY, prompt.VISUAL_PROMPT),
        (VISUAL_PROCESSING, prompt.VISUAL_PROCESSING_PROMPT),
        (VISUAL_UNAVAILABLE, prompt.VISUAL_UNAVAILABLE_PROMPT),
    ],
)
def test_the_visual_section_matches_whether_the_picture_can_be_looked_at(availability, section) -> None:
    converted = runner._model_history([], deps=ConversationDeps(video_id="video", visual_availability=availability))

    prompts = [message.parts[0].content for message in converted]
    visual_sections = {prompt.VISUAL_PROMPT, prompt.VISUAL_PROCESSING_PROMPT, prompt.VISUAL_UNAVAILABLE_PROMPT}
    assert [text for text in prompts if text in visual_sections] == [section]


def test_the_not_ready_sections_say_what_to_tell_the_user() -> None:
    assert prompt.VISUAL_PROCESSING_MESSAGE in prompt.VISUAL_PROCESSING_PROMPT
    assert prompt.VISUAL_UNAVAILABLE_MESSAGE in prompt.VISUAL_UNAVAILABLE_PROMPT
    for section in (prompt.VISUAL_PROCESSING_PROMPT, prompt.VISUAL_UNAVAILABLE_PROMPT):
        assert not any(tool in section for tool in VISUAL_TOOLS)


def test_the_visual_section_names_every_visual_tool_and_the_budget() -> None:
    for name in VISUAL_TOOLS:
        assert name in prompt.VISUAL_PROMPT
    assert "6 visual tool calls and 4 looks" in prompt.VISUAL_PROMPT


def test_the_viewer_s_position_comes_last_right_before_the_question() -> None:
    history = [
        StoredMessage("u", "current", "user", "What is on the slide?", None, NOW),
        StoredMessage("a", "current", "assistant", "A diagram.", None, NOW),
    ]
    deps = ConversationDeps(video_id="video", current_time_seconds=133.0, player_paused=True)

    converted = runner._model_history(history, deps=deps)

    assert converted[-2].parts[0].content == "A diagram."
    assert converted[-1].parts[0].content == prompt.viewer_position_prompt(133.0, True)


@pytest.mark.parametrize(
    ("time_seconds", "paused", "expected"),
    [
        (133.0, True, "paused at 02:13 (133.0 seconds)"),
        (133.0, False, "playing, at 02:13 (133.0 seconds)"),
        (133.0, None, "was at 02:13 (133.0 seconds)"),
        (None, None, "not known"),
    ],
)
def test_the_viewer_s_position_says_where_the_player_was_and_whether_it_was_paused(
    time_seconds, paused, expected
) -> None:
    assert expected in prompt.viewer_position_prompt(time_seconds, paused)


def test_system_prompt_does_not_embed_a_transcript() -> None:
    assert "The video data is only available through your tools" in runner.SYSTEM_PROMPT
    assert "full transcript" not in runner.SYSTEM_PROMPT.lower()


PROMPT_SOURCES = [Path(prompt.__file__), Path(image_analysis.__file__)]
ALL_PROMPTS = [
    prompt.SYSTEM_PROMPT,
    prompt.VISUAL_PROMPT,
    prompt.VISUAL_PROCESSING_PROMPT,
    prompt.VISUAL_UNAVAILABLE_PROMPT,
    image_analysis.SEQUENCE_ANALYSIS_PROMPT,
    image_analysis.CANDIDATES_ANALYSIS_PROMPT,
]


@pytest.mark.parametrize("source", PROMPT_SOURCES, ids=lambda path: path.name)
def test_the_prompt_files_compile_without_warnings_or_line_joins(source: Path) -> None:
    # An invalid escape such as `1\.` is only a SyntaxWarning, so it would pass a plain import.
    text = source.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(text, str(source), "exec")
    # Inside a prompt string, a backslash at a line's end joins two lines with no space between.
    assert [number for number, line in enumerate(text.splitlines(), start=1) if line.endswith("\\")] == []


@pytest.mark.parametrize("artifact", ["&#", "&nbsp;", "״", "\\:", "\\.", "\\-", "\\*"])
def test_no_prompt_carries_a_rich_text_editor_artifact(artifact: str) -> None:
    for text in ALL_PROMPTS:
        assert artifact not in text


def _text_of(events) -> str:
    return "".join(event.text for event in events if isinstance(event, runner.TextFragment))


def test_the_answer_reaches_the_reader_as_it_is_written() -> None:
    deps = ConversationDeps(video_id="video")
    agent = FakeStreamingAgent(
        [
            PartStartEvent(index=0, part=TextPart(content="The model")),
            PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=" is used")),
            PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=" last.")),
        ]
    )

    emitted = _run(agent, deps)

    assert [event.text for event in emitted] == ["The model", " is used", " last."]


def test_an_answer_citing_only_retrieved_moments_keeps_its_citation() -> None:
    deps = ConversationDeps(video_id="video")
    deps.retrieved.spans = list(RETRIEVED)

    emitted = _run(FakeStreamingAgent(_written("The model is used last. [12:14]")), deps)

    assert _text_of(emitted) == "The model is used last. [12:14]"


def test_a_citation_no_tool_returned_is_dropped_and_the_rest_of_the_answer_stands() -> None:
    deps = ConversationDeps(video_id="video")
    deps.retrieved.spans = list(RETRIEVED)

    emitted = _run(FakeStreamingAgent(_written("Grounded. [12:14] Invented. [13:05] Done.")), deps)

    assert _text_of(emitted) == "Grounded. [12:14] Invented. Done."


def test_a_moment_an_earlier_turn_retrieved_is_still_citable() -> None:
    deps = ConversationDeps(video_id="video")
    deps.retrieved.restore(RETRIEVED)

    emitted = _run(FakeStreamingAgent(_written("As said before. [12:14]")), deps)

    assert _text_of(emitted) == "As said before. [12:14]"


def test_a_moment_a_tool_returns_during_the_turn_becomes_citable() -> None:
    deps = ConversationDeps(video_id="video")
    result = {"memories": [{"start_seconds": 730.0, "end_seconds": 760.0}]}
    agent = FakeStreamingAgent(
        [
            FunctionToolCallEvent(part=ToolCallPart(tool_name="search", args={}, tool_call_id="call")),
            FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="search", content=result, tool_call_id="call")
            ),
            *_written("Found it. [12:14]"),
        ]
    )

    emitted = _run(agent, deps)

    assert deps.retrieved.spans == [(730.0, 760.0)]
    assert _text_of(emitted) == "Found it. [12:14]"


def test_text_written_before_and_after_a_tool_call_does_not_run_together() -> None:
    deps = ConversationDeps(video_id="video")
    agent = FakeStreamingAgent(
        [
            PartStartEvent(index=0, part=TextPart(content="Let me look.")),
            FunctionToolCallEvent(part=ToolCallPart(tool_name="search", args={}, tool_call_id="call")),
            FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="search", content={}, tool_call_id="call")
            ),
            PartStartEvent(index=0, part=TextPart(content="Here it is.")),
        ]
    )

    assert _text_of(_run(agent, deps)) == f"Let me look.{runner.PARAGRAPH_BREAK}Here it is."


def test_a_failure_while_streaming_reaches_the_caller() -> None:
    deps = ConversationDeps(video_id="video")
    agent = FakeStreamingAgent(_written("Half an answer"), failure=RuntimeError("model went away"))

    with pytest.raises(RuntimeError):
        _run(agent, deps)
