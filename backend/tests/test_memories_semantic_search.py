"""Tests for the conversation tool that searches a video's memories by meaning."""

import pytest
from pydantic_ai import RunContext

from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.memories_semantic_search import TOP_K, memories_semantic_search
from backend.video_agent.tools.memories_semantic_search import tool as tool_module
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
MEMORY_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
MEMORY_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"

ROWS = [
    {
        "memory_id": MEMORY_ID_1,
        "chapter_id": CHAPTER_ID,
        "text": "the aligner needs the audio at sixteen kilohertz, mono",
        "summary": "States the aligner's audio format.",
        "chapter_title": "Word alignment",
        "start_seconds": 90.0,
        "end_seconds": 104.5,
    },
    {
        "memory_id": MEMORY_ID_2,
        "chapter_id": None,
        "text": "and we cache the checkpoint so it only downloads once",
        "summary": "Notes the checkpoint is cached.",
        "chapter_title": None,
        "start_seconds": 210.25,
        "end_seconds": 228.0,
    },
]

QUERY_VECTOR = [0.1] * 384


def _context(deps: ConversationDeps) -> RunContext[ConversationDeps]:
    """A RunContext carrying nothing but the deps.

    Built field by field rather than through the constructor: Pydantic AI has changed which
    of RunContext's other fields are required across versions, and a tool that only reads
    `ctx.deps` should not have a test that breaks when a field it never touches is added.
    """
    context = object.__new__(RunContext)
    object.__setattr__(context, "deps", deps)
    return context


@pytest.fixture
def embedded_queries(monkeypatch) -> list[str]:
    """Records what was embedded, so a test never loads the real model's checkpoint."""
    recorded: list[str] = []

    def fake_embed_text(text: str) -> list[float]:
        recorded.append(text)
        return QUERY_VECTOR

    monkeypatch.setattr(tool_module, "embed_text", fake_embed_text)
    return recorded


def _search(query: str, rows: list[dict]) -> tuple[list, FakePool]:
    pool = FakePool(rows=rows)
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)
    return memories_semantic_search(_context(deps), query), pool


def test_the_query_is_embedded_as_written(embedded_queries) -> None:
    """Rows were indexed as a `chapter title: ... / memory summary: ...` string, but the
    query is embedded raw: it has no chapter title to give, so framing it the same way
    would only ever match the shape an ungrouped memory has.
    """
    _search("why does alignment need mono audio?", ROWS)

    assert embedded_queries == ["why does alignment need mono audio?"]


def test_the_search_is_scoped_to_the_video_in_deps_and_asks_for_five(embedded_queries) -> None:
    """The model supplies only the query. Which video is searched comes from the run's
    deps, so the agent cannot search a video the conversation is not about.
    """
    _, pool = _search("mono audio", ROWS)

    assert pool.recorded[0].parameters == (VIDEO_ID, QUERY_VECTOR, TOP_K)
    assert TOP_K == 5


def test_a_hit_carries_what_was_said_and_when(embedded_queries) -> None:
    hits, _ = _search("mono audio", ROWS)

    assert len(hits) == len(ROWS)
    assert hits[0].memory_id == MEMORY_ID_1
    assert hits[0].chapter_id == CHAPTER_ID
    assert hits[0].text == ROWS[0]["text"]
    assert hits[0].summary == ROWS[0]["summary"]
    assert hits[0].chapter_title == "Word alignment"
    assert (hits[0].start_seconds, hits[0].end_seconds) == (90.0, 104.5)


def test_a_hit_from_an_ungrouped_memory_has_no_chapter_title_or_id(embedded_queries) -> None:
    hits, _ = _search("checkpoint caching", ROWS)

    assert hits[1].chapter_title is None
    assert hits[1].chapter_id is None


def test_a_video_with_nothing_embedded_yields_no_hits_rather_than_an_error(embedded_queries) -> None:
    """Nothing found and nothing embedded look the same to the agent on purpose: both mean
    there is no spoken content to answer from, which it can say without a failed tool call.
    """
    hits, _ = _search("anything at all", [])

    assert hits == []
