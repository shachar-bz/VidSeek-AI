"""Tests for the conversation tool that shows the agent what YouTube commenters said."""

import asyncio

import pytest
from pydantic_ai import RunContext

from backend.video_agent import runner
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.get_viewer_comments import (
    MAX_COMMENTS,
    MAX_TEXT_CHARS,
    get_viewer_comments,
    only_for_a_video_with_comments,
    viewer_comments_tool,
)
from backend.video_agent.tools.get_viewer_comments import tool as tool_module
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
QUERY_VECTOR = [0.1] * 384


def _comment_row(comment_id: str, text: str, likes: int, replies: int = 0) -> dict:
    return {
        "id": comment_id,
        "video_id": VIDEO_ID,
        "author": "Someone",
        "text": text,
        "like_count": likes,
        "reply_count": replies,
        "published_at": "2026-09-14T10:00:00+00:00",
    }


COMMENT_ROWS = [
    _comment_row("c1", "The ending was rushed", 900, 40),
    _comment_row("c2", "Great explanation of the price model", 120, 2),
]


def _context(deps: ConversationDeps) -> RunContext[ConversationDeps]:
    """A RunContext carrying nothing but the deps; see test_memories_semantic_search."""
    context = object.__new__(RunContext)
    object.__setattr__(context, "deps", deps)
    return context


@pytest.fixture
def embedded_queries(monkeypatch) -> list[str]:
    """Records what was embedded, so a test never loads the real model."""
    recorded: list[str] = []

    def fake_embed_query(text: str) -> list[float]:
        recorded.append(text)
        return QUERY_VECTOR

    monkeypatch.setattr(tool_module, "embed_query", fake_embed_query)
    return recorded


def _call(responses: list[list[dict]], query: str | None = None):
    pool = FakePool(responses=responses)
    result = get_viewer_comments(_context(ConversationDeps(video_id=VIDEO_ID, pool=pool)), query)
    return result, pool


def test_without_a_query_the_most_liked_comments_come_back(embedded_queries) -> None:
    result, pool = _call([[{"comment_count": 2}], COMMENT_ROWS])

    assert result.matched_by == "top_liked"
    assert result.total_stored == 2
    assert [comment.text for comment in result.comments] == [
        "The ending was rushed",
        "Great explanation of the price model",
    ]
    assert (result.comments[0].like_count, result.comments[0].reply_count) == (900, 40)
    assert pool.recorded[1].parameters == (VIDEO_ID, MAX_COMMENTS)
    assert embedded_queries == []


def test_a_blank_query_is_treated_as_no_query(embedded_queries) -> None:
    result, _ = _call([[{"comment_count": 2}], COMMENT_ROWS], query="   ")

    assert result.matched_by == "top_liked"
    assert embedded_queries == []


def test_a_query_returns_the_comments_closest_in_meaning_with_no_cutoff(embedded_queries) -> None:
    """No similarity cutoff: e5 scores filler as close as real matches, so the agent judges."""
    result, pool = _call(
        [[{"comment_count": 2}], [{"embedded": True}], COMMENT_ROWS], query="the ending"
    )

    assert embedded_queries == ["the ending"]
    assert result.matched_by == "similarity"
    assert len(result.comments) == 2
    search = pool.recorded[2]
    assert search.parameters == (VIDEO_ID, QUERY_VECTOR, MAX_COMMENTS)
    assert "order by e.embedding <=> %s::vector" in search.statement


def test_a_video_whose_comments_were_never_embedded_falls_back_to_the_top_liked(
    embedded_queries,
) -> None:
    result, _ = _call([[{"comment_count": 2}], [{"embedded": False}], COMMENT_ROWS], query="ending")

    assert result.matched_by == "top_liked_fallback"
    assert len(result.comments) == 2
    assert embedded_queries == []


def test_a_long_comment_is_cut_and_marked(embedded_queries) -> None:
    long_row = _comment_row("c3", "x" * (MAX_TEXT_CHARS + 50), 5)
    result, _ = _call([[{"comment_count": 1}], [long_row]])

    assert result.comments[0].text == "x" * MAX_TEXT_CHARS + "…"


def test_no_author_reaches_the_agent(embedded_queries) -> None:
    result, _ = _call([[{"comment_count": 2}], COMMENT_ROWS])

    assert "author" not in result.comments[0].model_dump()


def test_every_result_says_what_the_comments_are_a_sample_of(embedded_queries) -> None:
    result, _ = _call([[{"comment_count": 2}], COMMENT_ROWS])

    assert "not what all viewers think" in result.sample


@pytest.mark.parametrize(("has_comments", "offered"), [(True, True), (False, False)])
def test_the_tool_is_offered_only_for_a_video_with_comments(has_comments, offered) -> None:
    deps = ConversationDeps(video_id=VIDEO_ID, has_comments=has_comments)
    definition = object()

    prepared = asyncio.run(only_for_a_video_with_comments(_context(deps), definition))

    assert (prepared is definition) is offered


def test_the_agent_carries_the_comments_tool_with_its_gate() -> None:
    assert viewer_comments_tool in runner.TOOLS
    assert viewer_comments_tool.prepare is only_for_a_video_with_comments


@pytest.mark.parametrize("has_comments", [True, False])
def test_the_comments_instructions_appear_only_where_the_tool_is_offered(has_comments) -> None:
    converted = runner._model_history(
        [], deps=ConversationDeps(video_id=VIDEO_ID, has_comments=has_comments)
    )
    prompts = [part.content for message in converted for part in message.parts]

    assert (runner.VIEWER_COMMENTS_PROMPT in prompts) is has_comments
