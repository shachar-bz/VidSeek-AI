"""Tests the agent's fixed model, tool set, and persisted-history conversion."""

from backend.storage.postgres import StoredMessage
from backend.video_agent import runner
from backend.video_agent.tools.deps import ConversationDeps

NOW = "2026-09-19T10:00:00+00:00"


def test_agent_selects_the_requested_model_and_all_five_tools(monkeypatch) -> None:
    captured = {}

    class FakeAgent:
        def __init__(self, model, **kwargs):
            captured.update(model=model, **kwargs)

    monkeypatch.setattr(runner, "Agent", FakeAgent)
    built = runner.build_agent()

    assert isinstance(built, FakeAgent)
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
