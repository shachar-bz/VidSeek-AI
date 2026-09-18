"""Tests for the `memory_embeddings` table one vector per memory is written to."""

from backend.storage.postgres.memory_embeddings import (
    TABLE_NAME,
    MemoryEmbedding,
    PostgresMemoryEmbeddings,
)
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID = "66666666-7777-8888-9999-000000000000"
MEMORY_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
MEMORY_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"

EMBEDDINGS = [
    MemoryEmbedding(
        memory_id=MEMORY_ID_1,
        chapter_id=CHAPTER_ID,
        embedding=[0.1, 0.2, 0.3],
        model="all-MiniLM-L6-v2",
        dimensions=3,
    ),
    MemoryEmbedding(
        memory_id=MEMORY_ID_2,
        chapter_id=None,
        embedding=[0.4, 0.5, 0.6],
        model="all-MiniLM-L6-v2",
        dimensions=3,
    ),
]


def _store(rows: list[dict] | None = None) -> tuple[PostgresMemoryEmbeddings, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresMemoryEmbeddings(pool=pool), pool


def test_embeddings_are_written_as_one_statement_per_batch_not_per_memory() -> None:
    store, pool = _store()
    written = store.replace(VIDEO_ID, EMBEDDINGS)

    assert written == len(EMBEDDINGS)
    assert pool.recorded[0].many is True
    assert len(pool.recorded[0].parameters) == len(EMBEDDINGS)


def test_a_memory_embedding_carries_its_chapter_model_and_dimensions() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert pool.recorded[0].parameters[0] == (
        MEMORY_ID_1,
        VIDEO_ID,
        CHAPTER_ID,
        [0.1, 0.2, 0.3],
        "all-MiniLM-L6-v2",
        3,
    )


def test_a_memory_with_no_chapter_yet_is_written_with_a_null_chapter_id() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert pool.recorded[0].parameters[1][2] is None


def test_a_re_embedded_memory_is_overwritten_in_place() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert "on conflict (memory_id) do update set" in pool.statements[0]
    assert "embedding = excluded.embedding" in pool.statements[0]


def test_memories_the_new_run_did_not_produce_are_dropped() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert "memory_id != all(%s)" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, [MEMORY_ID_1, MEMORY_ID_2])


def test_a_run_that_produced_nothing_clears_the_video_s_embeddings() -> None:
    store, pool = _store()
    written = store.replace(VIDEO_ID, [])

    assert written == 0
    assert not any(item.many for item in pool.recorded)
    assert pool.recorded[-1].parameters == (VIDEO_ID, [])


def test_the_write_and_the_trim_are_one_transaction() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert pool.transactions == 1


def test_memories_for_video_reads_the_chapter_title_alongside_the_summary() -> None:
    rows = [
        {
            "memory_id": MEMORY_ID_1,
            "video_id": VIDEO_ID,
            "chapter_id": CHAPTER_ID,
            "chapter_title": "Getting started",
            "summary": "The host explains the setup.",
            "text": "Okay, so first you plug it in.",
        }
    ]
    store, pool = _store(rows)
    memories = store.memories_for_video(VIDEO_ID)

    assert len(memories) == 1
    assert memories[0].chapter_title == "Getting started"
    assert memories[0].summary == "The host explains the setup."
    assert memories[0].text == "Okay, so first you plug it in."
    assert "left join public.chapters" in pool.statements[0]
    assert "order by m.memory_index" in pool.statements[0]


def test_memories_for_video_leaves_the_chapter_title_none_when_ungrouped() -> None:
    rows = [
        {
            "memory_id": MEMORY_ID_2,
            "video_id": VIDEO_ID,
            "chapter_id": None,
            "chapter_title": None,
            "summary": "A moment with no chapter yet.",
            "text": "Some raw speech.",
        }
    ]
    store, _ = _store(rows)
    memories = store.memories_for_video(VIDEO_ID)

    assert memories[0].chapter_id is None
    assert memories[0].chapter_title is None


def test_deleting_embeddings_is_scoped_to_one_video() -> None:
    store, pool = _store()
    store.delete(VIDEO_ID)

    assert pool.statements[0] == f"delete from public.{TABLE_NAME} where video_id = %s::uuid"
    assert pool.recorded[0].parameters == (VIDEO_ID,)


MATCH_ROWS = [
    {
        "memory_id": MEMORY_ID_1,
        "chapter_id": CHAPTER_ID,
        "text": "and that is why the alignment step runs before transcription is stored",
        "summary": "Explains why alignment precedes storage.",
        "chapter_title": "The transcription pipeline",
        "start_seconds": 12.5,
        "end_seconds": 31.0,
    },
    {
        "memory_id": MEMORY_ID_2,
        "chapter_id": None,
        "text": "the second thing worth knowing about embeddings",
        "summary": "Introduces embeddings.",
        "chapter_title": None,
        "start_seconds": 44.0,
        "end_seconds": 58.25,
    },
]

QUERY_VECTOR = [0.7, 0.8, 0.9]


def test_search_orders_by_cosine_distance_and_filters_to_the_one_video() -> None:
    store, pool = _store(MATCH_ROWS)
    store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5)

    statement = pool.statements[0]
    assert "e.embedding <=> %s::vector" in statement
    assert "where e.video_id = %s::uuid" in statement
    assert pool.recorded[0].parameters == (VIDEO_ID, QUERY_VECTOR, 5)


def test_search_reaches_the_video_through_the_embeddings_table_not_through_memories() -> None:
    """The video filter is on `memory_embeddings.video_id`, which 0010 denormalized onto it
    for exactly this: filtering through `memories` instead would join the whole table first.
    """
    store, pool = _store(MATCH_ROWS)
    store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5)

    statement = pool.statements[0]
    assert "m.video_id" not in statement
    assert "join public.memories m on m.id = e.memory_id" in statement


def test_search_keeps_a_memory_that_was_never_grouped_into_a_chapter() -> None:
    """A memory embedded before the chapter-grouping stage ran still matches, so the
    chapter join is a left one and its title comes back as None rather than dropping the row.
    """
    store, pool = _store(MATCH_ROWS)
    matches = store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5)

    assert "left join public.chapters" in pool.statements[0]
    assert [match.chapter_title for match in matches] == ["The transcription pipeline", None]


def test_search_answers_with_what_was_said_and_when() -> None:
    store, _ = _store(MATCH_ROWS)
    matches = store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5)

    assert len(matches) == len(MATCH_ROWS)
    first = matches[0]
    assert first.memory_id == MEMORY_ID_1
    assert first.chapter_id == CHAPTER_ID
    assert first.text == MATCH_ROWS[0]["text"]
    assert first.summary == MATCH_ROWS[0]["summary"]
    assert (first.start_seconds, first.end_seconds) == (12.5, 31.0)


def test_search_leaves_the_chapter_id_none_when_ungrouped() -> None:
    store, _ = _store(MATCH_ROWS)
    matches = store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5)

    assert matches[1].chapter_id is None


def test_search_of_a_video_with_nothing_embedded_returns_no_matches() -> None:
    store, _ = _store([])

    assert store.nearest_memories(VIDEO_ID, QUERY_VECTOR, 5) == []
