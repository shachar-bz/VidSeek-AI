"""Tests for the `video_insights` table: a video's generated summary and takeaways."""

import pytest

from backend.storage.postgres import NewVideoInsights, PostgresVideoInsights, StoredVideoInsights
from backend.storage.postgres.video_insights import TABLE_NAME
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-1111-1111-1111-111111111111"

NEW_INSIGHTS = NewVideoInsights(
    video_id=VIDEO_ID,
    summary="A talk about testing.",
    takeaways=["Write tests first", "Keep them fast"],
    suggested_questions=["What is a fake pool?"],
    model="gpt-5.6-sol",
)

ROW = {
    "video_id": VIDEO_ID,
    "summary": NEW_INSIGHTS.summary,
    "takeaways": NEW_INSIGHTS.takeaways,
    "suggested_questions": NEW_INSIGHTS.suggested_questions,
    "model": NEW_INSIGHTS.model,
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}


def _insights(rows: list[dict] | None = None) -> tuple[PostgresVideoInsights, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresVideoInsights(pool=pool), pool


def test_insights_are_upserted_against_the_video_they_describe() -> None:
    insights, pool = _insights([ROW])
    stored = insights.upsert(NEW_INSIGHTS)

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert "on conflict (video_id) do update set" in pool.statements[0]
    assert stored == StoredVideoInsights(
        video_id=VIDEO_ID,
        summary=NEW_INSIGHTS.summary,
        takeaways=NEW_INSIGHTS.takeaways,
        suggested_questions=NEW_INSIGHTS.suggested_questions,
        model=NEW_INSIGHTS.model,
        created_at=ROW["created_at"],
        updated_at=ROW["updated_at"],
    )


def test_a_second_generation_replaces_the_first_rather_than_adding_to_it() -> None:
    insights, pool = _insights([ROW])
    insights.upsert(NEW_INSIGHTS)

    assert pool.recorded[0].parameters == (
        VIDEO_ID,
        NEW_INSIGHTS.summary,
        NEW_INSIGHTS.takeaways,
        NEW_INSIGHTS.suggested_questions,
        NEW_INSIGHTS.model,
    )


def test_an_upsert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    insights, _ = _insights([])

    with pytest.raises(RuntimeError, match="returned no row"):
        insights.upsert(NEW_INSIGHTS)


def test_a_video_with_no_insights_yet_is_absence_rather_than_an_error() -> None:
    insights, _ = _insights([])

    assert insights.get(VIDEO_ID) is None


def test_reading_insights_back_returns_the_stored_lists() -> None:
    insights, _ = _insights([ROW])
    found = insights.get(VIDEO_ID)

    assert found is not None
    assert found.takeaways == NEW_INSIGHTS.takeaways
    assert found.suggested_questions == NEW_INSIGHTS.suggested_questions


def test_a_column_this_backend_does_not_know_about_is_ignored() -> None:
    stored = StoredVideoInsights.from_row({**ROW, "embedding_model": "text-embedding-3-small"})

    assert stored.video_id == VIDEO_ID
