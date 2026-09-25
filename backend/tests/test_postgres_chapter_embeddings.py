"""Tests for the `chapter_embeddings` table one vector per chapter is written to."""

from backend.storage.postgres.chapter_embeddings import (
    TABLE_NAME,
    ChapterEmbedding,
    PostgresChapterEmbeddings,
)
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
CHAPTER_ID_1 = "aaaaaaaa-1111-1111-1111-111111111111"
CHAPTER_ID_2 = "bbbbbbbb-2222-2222-2222-222222222222"

EMBEDDINGS = [
    ChapterEmbedding(
        chapter_id=CHAPTER_ID_1,
        start_seconds=0.0,
        end_seconds=30.0,
        embedding=[0.1, 0.2, 0.3],
        model="intfloat/multilingual-e5-small",
        dimensions=3,
    ),
    ChapterEmbedding(
        chapter_id=CHAPTER_ID_2,
        start_seconds=30.0,
        end_seconds=90.0,
        embedding=[0.4, 0.5, 0.6],
        model="intfloat/multilingual-e5-small",
        dimensions=3,
    ),
]


def _store(rows: list[dict] | None = None) -> tuple[PostgresChapterEmbeddings, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresChapterEmbeddings(pool=pool), pool


def test_embeddings_are_written_as_one_statement_per_batch_not_per_chapter() -> None:
    store, pool = _store()
    written = store.replace(VIDEO_ID, EMBEDDINGS)

    assert written == len(EMBEDDINGS)
    assert pool.recorded[0].many is True
    assert len(pool.recorded[0].parameters) == len(EMBEDDINGS)


def test_a_chapter_embedding_carries_its_timing_model_and_dimensions() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert pool.recorded[0].parameters[0] == (
        CHAPTER_ID_1,
        VIDEO_ID,
        0.0,
        30.0,
        [0.1, 0.2, 0.3],
        "intfloat/multilingual-e5-small",
        3,
    )


def test_a_re_embedded_chapter_is_overwritten_in_place() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert "on conflict (chapter_id) do update set" in pool.statements[0]
    assert "embedding = excluded.embedding" in pool.statements[0]


def test_chapters_the_new_run_did_not_produce_are_dropped() -> None:
    store, pool = _store()
    store.replace(VIDEO_ID, EMBEDDINGS)

    assert "chapter_id != all(%s)" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, [CHAPTER_ID_1, CHAPTER_ID_2])


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


def test_chapters_for_video_reads_the_title_summary_and_timing() -> None:
    rows = [
        {
            "chapter_id": CHAPTER_ID_1,
            "video_id": VIDEO_ID,
            "title": "Getting started",
            "summary": "The host explains the setup.",
            "start_seconds": 0.0,
            "end_seconds": 30.0,
        }
    ]
    store, pool = _store(rows)
    chapters = store.chapters_for_video(VIDEO_ID)

    assert len(chapters) == 1
    assert chapters[0].title == "Getting started"
    assert chapters[0].summary == "The host explains the setup."
    assert chapters[0].start_seconds == 0.0
    assert chapters[0].end_seconds == 30.0
    assert "order by chapter_index" in pool.statements[0]


def test_deleting_embeddings_is_scoped_to_one_video() -> None:
    store, pool = _store()
    store.delete(VIDEO_ID)

    assert pool.statements[0] == f"delete from public.{TABLE_NAME} where video_id = %s::uuid"
    assert pool.recorded[0].parameters == (VIDEO_ID,)
