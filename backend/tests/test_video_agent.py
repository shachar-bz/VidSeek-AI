"""Tests the agent's fixed model, tool set, citation check, and persisted-history conversion."""

import asyncio

import pytest
from pydantic_ai import (
    AgentRunResultEvent,
    ModelRetry,
    PartDeltaEvent,
    PartStartEvent,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import TextPart, TextPartDelta

from backend.storage.postgres import StoredMessage
from backend.video_agent import runner
from backend.video_agent.tools.deps import ConversationDeps

NOW = "2026-09-19T10:00:00+00:00"
RETRIEVED = [(730.0, 760.0)]


class FakeRunContext:
    """The single attribute the citation check reads off a RunContext."""

    def __init__(self, deps: ConversationDeps):
        self.deps = deps


class FakeEventStream:
    """One agent run's events, optionally ending the way a spent retry budget ends it."""

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


def test_agent_selects_the_requested_model_and_all_five_tools(monkeypatch) -> None:
    captured = {}

    class FakeAgent:
        def __init__(self, model, **kwargs):
            captured.update(model=model, **kwargs)
            self.validators = []

        def output_validator(self, validator):
            self.validators.append(validator)
            return validator

    monkeypatch.setattr(runner, "Agent", FakeAgent)
    built = runner.build_agent()

    assert isinstance(built, FakeAgent)
    assert built.validators == [runner._verify_citations]
    assert captured["model"] == "openai:gpt-5.6-terra"
    assert captured["defer_model_check"] is True
    assert {tool.__name__ for tool in captured["tools"]} == {
        "get_video_info",
        "get_video_outline",
        "memories_semantic_search",
        "get_chapter_context",
        "get_memory_context",
    }
    assert "sole source of evidence" in captured["system_prompt"]


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


def test_system_prompt_does_not_embed_a_transcript() -> None:
    assert "The video data is only available through your tools" in runner.SYSTEM_PROMPT
    assert "full transcript" not in runner.SYSTEM_PROMPT.lower()


def test_partial_video_history_warns_that_timestamps_may_be_unreliable() -> None:
    converted = runner._model_history(
        [], deps=ConversationDeps(video_id="video", timestamps_reliable=False)
    )

    assert converted[1].parts[0].content == runner.PARTIAL_TIMING_PROMPT


def test_an_answer_citing_only_retrieved_moments_is_accepted() -> None:
    deps = ConversationDeps(video_id="video")
    deps.draft.spans = list(RETRIEVED)

    answer = "The model is used last. [12:14]"

    assert runner._verify_citations(FakeRunContext(deps), answer) == answer


def test_an_invented_citation_is_sent_back_for_a_rewrite() -> None:
    deps = ConversationDeps(video_id="video")
    deps.draft.spans = list(RETRIEVED)

    with pytest.raises(ModelRetry) as raised:
        runner._verify_citations(FakeRunContext(deps), "Claimed without evidence. [13:05]")

    assert "[13:05]" in str(raised.value)


def test_a_refused_answer_is_kept_so_it_can_be_delivered_without_its_bad_citation() -> None:
    deps = ConversationDeps(video_id="video")
    deps.draft.spans = list(RETRIEVED)

    with pytest.raises(ModelRetry):
        runner._verify_citations(FakeRunContext(deps), "Grounded. [12:14] Invented. [13:05]")

    assert deps.draft.rejected is True
    assert deps.draft.verifiable_text() == "Grounded. [12:14] Invented."


def test_no_text_reaches_the_reader_before_the_checked_answer_does() -> None:
    deps = ConversationDeps(video_id="video")
    answer = "The model is used last. [12:14]"
    agent = FakeStreamingAgent(
        [*_written(answer), AgentRunResultEvent(result=_FakeResult(answer))]
    )

    emitted = _run(agent, deps)

    assert [event.text for event in emitted] == [answer]


def test_an_answer_that_never_passed_the_check_is_delivered_without_its_citations() -> None:
    deps = ConversationDeps(video_id="video")
    deps.draft.spans = list(RETRIEVED)
    deps.draft.rejected = True
    agent = FakeStreamingAgent(
        _written("Grounded. [12:14] Invented. [13:05]"),
        failure=UnexpectedModelBehavior("Exceeded maximum output retries (1)"),
    )

    emitted = _run(agent, deps)

    assert [event.text for event in emitted] == ["Grounded. [12:14] Invented."]


def test_unexpected_behaviour_that_is_not_a_refused_citation_still_fails() -> None:
    deps = ConversationDeps(video_id="video")
    agent = FakeStreamingAgent(
        _written("Half an answer"), failure=UnexpectedModelBehavior("Received empty response")
    )

    with pytest.raises(UnexpectedModelBehavior):
        _run(agent, deps)


class _FakeResult:
    def __init__(self, output: str):
        self.output = output
