"""Tests for the conversation tool that searches a video's memories by meaning.

Which memories count as hits is `services/memory_search.py`'s rule and is tested in
`test_memory_search`; these tests are about what the tool hands the model.
"""

import pytest
from pydantic_ai import RunContext

from backend.services import memory_search as memory_search_module
from backend.video_agent.citations import spans_of
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.memories_semantic_search import MemorySearchResult, memories_semantic_search
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
MEMORY_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
MEMORY_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"

ALIGNER_ROW = {
    "memory_id": MEMORY_ID_1,
    "chapter_id": CHAPTER_ID,
    "text": "the aligner needs the audio at sixteen kilohertz, mono",
    "summary": "States the aligner's audio format.",
    "chapter_title": "Word alignment",
    "start_seconds": 90.0,
    "end_seconds": 104.5,
    "similarity": 0.90,
}
CHECKPOINT_ROW = {
    "memory_id": MEMORY_ID_2,
    "chapter_id": None,
    "text": "and we cache the checkpoint so it only downloads once",
    "summary": "Notes the checkpoint is cached.",
    "chapter_title": None,
    "start_seconds": 210.25,
    "end_seconds": 228.0,
    "similarity": 0.90,
}


def _background_row(index: int) -> dict:
    """A memory that scores like the rest of the video, so that a 0.90 stands out against it."""
    return {
        "memory_id": f"cccccccc-0000-0000-0000-{index:012d}",
        "chapter_id": CHAPTER_ID,
        "text": f"unrelated speech number {index}",
        "summary": "Something else entirely.",
        "chapter_title": "Word alignment",
        "start_seconds": 300.0 + index * 20,
        "end_seconds": 310.0 + index * 20,
        "similarity": 0.80,
    }


# Two memories at 0.90 among eight at 0.80: both stand out (z 2.0), the rest do not.
STANDOUT_ROWS = [ALIGNER_ROW, CHECKPOINT_ROW] + [_background_row(index) for index in range(8)]

# Two memories only, a little apart: neither can stand out from the other (z +-1.0).
NOTHING_STANDS_OUT_ROWS = [ALIGNER_ROW, {**CHECKPOINT_ROW, "similarity": 0.85}]

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

    def fake_embed_query(text: str) -> list[float]:
        recorded.append(text)
        return QUERY_VECTOR

    monkeypatch.setattr(memory_search_module, "embed_query", fake_embed_query)
    return recorded


def _search(query: str, rows: list[dict]) -> tuple[MemorySearchResult, FakePool]:
    pool = FakePool(rows=rows)
    deps = ConversationDeps(video_id=VIDEO_ID, pool=pool)
    return memories_semantic_search(_context(deps), query), pool


def test_the_query_is_embedded_as_written(embedded_queries) -> None:
    """Rows were indexed as a `chapter title: ... / memory summary: ...` string, but the
    query is embedded raw: it has no chapter title to give, so framing it the same way
    would only ever match the shape an ungrouped memory has. (`embed_query` adds e5's
    `query: ` prefix itself.)
    """
    _search("why does alignment need mono audio?", STANDOUT_ROWS)

    assert embedded_queries == ["why does alignment need mono audio?"]


def test_the_search_is_scoped_to_the_video_in_deps(embedded_queries) -> None:
    """The model supplies only the query. Which video is searched comes from the run's
    deps, so the agent cannot search a video the conversation is not about.
    """
    _, pool = _search("mono audio", STANDOUT_ROWS)

    assert pool.recorded[0].parameters == (QUERY_VECTOR, VIDEO_ID, "intfloat/multilingual-e5-small")


def test_only_vectors_from_the_query_model_are_compared(embedded_queries) -> None:
    """A video still holding MiniLM vectors must not have them ranked against an e5 query."""
    _, pool = _search("mono audio", STANDOUT_ROWS)

    assert "e.model = %s" in pool.statements[0]


def test_only_the_moments_that_stand_out_come_back_and_no_note_with_them(embedded_queries) -> None:
    result, _ = _search("mono audio", STANDOUT_ROWS)

    assert [moment.memory_id for moment in result.moments] == [MEMORY_ID_1, MEMORY_ID_2]
    assert not any(moment.weak for moment in result.moments)
    assert result.note is None


def test_a_moment_carries_what_was_said_and_when(embedded_queries) -> None:
    result, _ = _search("mono audio", STANDOUT_ROWS)
    first = result.moments[0]

    assert first.memory_id == MEMORY_ID_1
    assert first.chapter_id == CHAPTER_ID
    assert first.text == ALIGNER_ROW["text"]
    assert first.summary == ALIGNER_ROW["summary"]
    assert first.chapter_title == "Word alignment"
    assert (first.start_seconds, first.end_seconds) == (90.0, 104.5)


def test_a_moment_from_an_ungrouped_memory_has_no_chapter_title_or_id(embedded_queries) -> None:
    result, _ = _search("checkpoint caching", STANDOUT_ROWS)

    assert result.moments[1].chapter_title is None
    assert result.moments[1].chapter_id is None


def test_no_score_reaches_the_model(embedded_queries) -> None:
    """The agent judges a moment by what it says; `weak` is all it is told about how it was found."""
    result, _ = _search("mono audio", STANDOUT_ROWS)

    fields = set(result.moments[0].model_dump())
    assert fields == {
        "memory_id", "chapter_id", "chapter_title", "summary", "text",
        "start_seconds", "end_seconds", "weak",
    }


def test_when_nothing_stands_out_the_closest_come_back_weak_with_a_note(embedded_queries) -> None:
    result, _ = _search("something the video never mentions", NOTHING_STANDS_OUT_ROWS)

    assert [moment.memory_id for moment in result.moments] == [MEMORY_ID_1, MEMORY_ID_2]
    assert all(moment.weak for moment in result.moments)
    assert result.note == (
        "Nothing stood out for this query: these are only the closest moments, marked weak, "
        "and they are probably not what was asked for."
    )


def test_a_weak_moment_is_still_citable(embedded_queries) -> None:
    """A weak moment is speech actually retrieved, not a frame nobody has looked at, so its
    times are collected for the citation check the same as a hit's.
    """
    result, _ = _search("something the video never mentions", NOTHING_STANDS_OUT_ROWS)

    assert spans_of(result) == [(90.0, 104.5), (210.25, 228.0)]


def test_hits_are_citable_through_the_wrapping_result(embedded_queries) -> None:
    result, _ = _search("mono audio", STANDOUT_ROWS)

    assert spans_of(result) == [(90.0, 104.5), (210.25, 228.0)]


def test_a_video_with_nothing_embedded_yields_no_moments_rather_than_an_error(embedded_queries) -> None:
    """Nothing embedded is answered with an empty result and a note saying so, which the
    agent can pass on without a failed tool call.
    """
    result, _ = _search("anything at all", [])

    assert result.moments == []
    assert result.note == "There was nothing to search: this video has no stored moments of what was said."
