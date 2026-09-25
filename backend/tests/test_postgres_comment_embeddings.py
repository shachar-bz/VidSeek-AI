"""Tests for the `comment_embeddings` table a YouTube video's comment vectors are written to."""

from backend.storage.postgres import CommentEmbedding, PostgresCommentEmbeddings
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"
VECTOR = [0.5] * 384


def test_a_replace_writes_every_vector_in_one_batch_and_trims_the_rest_in_one_transaction() -> None:
    pool = FakePool()
    written = PostgresCommentEmbeddings(pool=pool).replace(
        VIDEO_ID,
        [
            CommentEmbedding(comment_id="c1", embedding=VECTOR, model="e5"),
            CommentEmbedding(comment_id="c2", embedding=VECTOR, model="e5"),
        ],
    )

    assert written == 2
    assert pool.transactions == 1
    assert pool.recorded[0].many is True
    assert pool.recorded[0].parameters[0] == ("c1", VIDEO_ID, VECTOR, "e5")
    assert pool.recorded[1].parameters == (VIDEO_ID, ["c1", "c2"])
    assert "delete from public.comment_embeddings" in pool.recorded[1].statement


def test_an_empty_replace_clears_the_video() -> None:
    pool = FakePool()
    PostgresCommentEmbeddings(pool=pool).replace(VIDEO_ID, [])

    assert len(pool.recorded) == 1
    assert pool.recorded[0].parameters == (VIDEO_ID, [])


def test_has_any_reads_the_exists_answer() -> None:
    assert PostgresCommentEmbeddings(pool=FakePool(rows=[{"embedded": True}])).has_any(VIDEO_ID)
    assert not PostgresCommentEmbeddings(pool=FakePool(rows=[{"embedded": False}])).has_any(VIDEO_ID)
