"""Tests for the conversation tool that searches what was said in a video.

How memories are ranked (meaning and exact words, fused) is `services/memory_search.py`'s rule
and is tested in `test_memory_search`; these tests replace the service with a fake and are about
what the tool hands the model.
"""

import importlib

import pytest
from pydantic_ai import RunContext

from backend.storage.postgres import ScoredMemory
from backend.video_agent.citations import spans_of
from backend.video_agent.tools.deps import ConversationDeps
from backend.video_agent.tools.search_video_speech import MemorySearchResult, search_video_speech

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
MEMORY_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
MEMORY_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"

ALIGNER_MEMORY = ScoredMemory(
    memory_id=MEMORY_ID_1,
    chapter_id=CHAPTER_ID,
    text="the aligner needs the audio at sixteen kilohertz, mono",
    summary="States the aligner's audio format.",
    chapter_title="Word alignment",
    start_seconds=90.0,
    end_seconds=104.5,
    similarity=0.90,
)
CHECKPOINT_MEMORY = ScoredMemory(
    memory_id=MEMORY_ID_2,
    chapter_id=None,
    text="and we cache the checkpoint so it only downloads once",
    summary="Notes the checkpoint is cached.",
    chapter_title=None,
    start_seconds=210.25,
    end_seconds=228.0,
    similarity=0.95,
)

POOL = object()

# The tool's module, where `search_memories` is looked up; imported by name because the
# package re-exports a function of the same name as the folder.
SEARCH_VIDEO_SPEECH_TOOL_MODULE = importlib.import_module("backend.video_agent.tools.search_video_speech.tool")


def _context(deps: ConversationDeps) -> RunContext[ConversationDeps]:
    """A RunContext carrying nothing but the deps.

    Built field by field rather than through the constructor: Pydantic AI has changed which
    of RunContext's other fields are required across versions, and a tool that only reads
    `ctx.deps` should not have a test that breaks when a field it never touches is added.
    """
    context = object.__new__(RunContext)
    object.__setattr__(context, "deps", deps)
    return context


class FakeSearchMemories:
    """Stands in for `search_memories`: returns fixed memories and records how it was called."""

    def __init__(self, memories: list[ScoredMemory]) -> None:
        self.memories = memories
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, video_id: str, query: str, *, pool=None, **_settings) -> list[ScoredMemory]:
        self.calls.append((video_id, query, pool))
        return list(self.memories)


@pytest.fixture
def fake_search(monkeypatch):
    """Installs a fake service in the tool's module; set `.memories` before searching."""
    fake = FakeSearchMemories([ALIGNER_MEMORY, CHECKPOINT_MEMORY])
    monkeypatch.setattr(SEARCH_VIDEO_SPEECH_TOOL_MODULE, "search_memories", fake)
    return fake


def _search(query: str) -> MemorySearchResult:
    deps = ConversationDeps(video_id=VIDEO_ID, pool=POOL)
    return search_video_speech(_context(deps), query)


def test_the_query_and_the_video_in_deps_are_passed_to_the_service(fake_search) -> None:
    """The model supplies only the query. Which video is searched comes from the run's
    deps, so the agent cannot search a video the conversation is not about.
    """
    _search("why does alignment need mono audio?")

    assert fake_search.calls == [(VIDEO_ID, "why does alignment need mono audio?", POOL)]


def test_moments_come_back_in_the_order_the_service_ranked_them(fake_search) -> None:
    """The service's order is the fused rank, not similarity: the tool must not re-sort."""
    result = _search("mono audio")

    assert [moment.memory_id for moment in result.moments] == [MEMORY_ID_1, MEMORY_ID_2]
    assert result.note is None


def test_a_moment_carries_what_was_said_and_when(fake_search) -> None:
    first = _search("mono audio").moments[0]

    assert first.memory_id == MEMORY_ID_1
    assert first.chapter_id == CHAPTER_ID
    assert first.chapter_title == "Word alignment"
    assert first.summary == ALIGNER_MEMORY.summary
    assert first.text == ALIGNER_MEMORY.text
    assert (first.start_seconds, first.end_seconds) == (90.0, 104.5)


def test_a_moment_from_an_ungrouped_memory_has_no_chapter_title_or_id(fake_search) -> None:
    second = _search("checkpoint caching").moments[1]

    assert second.chapter_title is None
    assert second.chapter_id is None


def test_no_score_or_relevance_flag_reaches_the_model(fake_search) -> None:
    """The agent judges a moment by what it says: no similarity, and no `weak` flag."""
    fields = set(_search("mono audio").moments[0].model_dump())

    assert fields == {
        "memory_id", "chapter_id", "chapter_title", "summary", "text",
        "start_seconds", "end_seconds",
    }


def test_moments_are_citable_through_the_wrapping_result(fake_search) -> None:
    assert spans_of(_search("mono audio")) == [(90.0, 104.5), (210.25, 228.0)]


def test_a_video_with_nothing_stored_yields_no_moments_and_a_note(fake_search) -> None:
    """Nothing stored is answered with an empty result and a note saying so, which the
    agent can pass on without a failed tool call.
    """
    fake_search.memories = []

    result = _search("anything at all")

    assert result.moments == []
    assert result.note == "There was nothing to search: this video has no stored moments of what was said."
    assert spans_of(result) == []
