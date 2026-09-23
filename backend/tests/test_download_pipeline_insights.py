"""Tests stage five stores validated insights and turns every failure into a problem."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.download_pipeline.insights import generate_and_store_insights
from backend.download_pipeline.result import INSIGHT_GENERATION_FAILED
from backend.services.video_insights import GeneratedVideoInsights, InsightGenerationError
from backend.storage.postgres import NewVideoInsights

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def _chapters_store():
    store = SimpleNamespace()
    store.video_outline = lambda video_id: [SimpleNamespace(chapter_id="chapter-1")]
    store.chapter_with_memories = lambda video_id, chapter_id: SimpleNamespace(
        title="Testing safely",
        summary="The chapter explains test isolation.",
        memories=[
            SimpleNamespace(
                summary="Dependencies are replaced with fakes.",
                text="raw transcript words that must never reach the model",
            ),
            SimpleNamespace(
                summary="Assertions focus on public behavior.",
                text="more raw transcript words",
            ),
        ],
    )
    return store


def test_validated_output_is_built_from_stored_summaries_and_upserted() -> None:
    generated = GeneratedVideoInsights(
        summary="A practical guide to isolated tests.",
        takeaways=["Replace external dependencies"],
        suggested_questions=["How do fakes keep tests deterministic?"],
    )

    with (
        patch(
            "backend.download_pipeline.insights.PostgresChapters",
            return_value=_chapters_store(),
        ),
        patch(
            "backend.download_pipeline.insights.generate_video_insights",
            return_value=generated,
        ) as generate,
        patch("backend.download_pipeline.insights.PostgresVideoInsights") as insights_store,
    ):
        result = generate_and_store_insights(VIDEO_ID, pool="pool")

    assert result.stored is True
    assert result.problems == ()
    chapters = generate.call_args.args[0]
    assert chapters[0].title == "Testing safely"
    assert chapters[0].summary == "The chapter explains test isolation."
    assert chapters[0].memory_summaries == (
        "Dependencies are replaced with fakes.",
        "Assertions focus on public behavior.",
    )
    insights_store.assert_called_once_with(pool="pool")
    insights_store.return_value.upsert.assert_called_once_with(
        NewVideoInsights(
            video_id=VIDEO_ID,
            summary=generated.summary,
            takeaways=generated.takeaways,
            suggested_questions=generated.suggested_questions,
            model="gpt-6-luna",
        )
    )


def test_service_exceptions_are_reported_without_escaping_or_writing() -> None:
    with (
        patch(
            "backend.download_pipeline.insights.PostgresChapters",
            return_value=_chapters_store(),
        ),
        patch(
            "backend.download_pipeline.insights.generate_video_insights",
            side_effect=InsightGenerationError("invalid output"),
        ),
        patch("backend.download_pipeline.insights.PostgresVideoInsights") as insights_store,
    ):
        result = generate_and_store_insights(VIDEO_ID)

    assert result.stored is False
    assert result.problems == (INSIGHT_GENERATION_FAILED,)
    insights_store.return_value.upsert.assert_not_called()


@pytest.mark.parametrize(
    "parsed",
    [
        None,
        GeneratedVideoInsights.model_construct(
            summary="Summary",
            takeaways=["one", "two", "three", "four", "five", "six"],
            suggested_questions=["Question?"],
        ),
    ],
)
def test_absent_or_invalid_structured_output_becomes_the_stage_problem(parsed) -> None:
    response = SimpleNamespace(output_parsed=parsed, status="completed")
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **_kwargs: response)
    )
    with (
        patch(
            "backend.download_pipeline.insights.PostgresChapters",
            return_value=_chapters_store(),
        ),
        patch("backend.download_pipeline.insights.PostgresVideoInsights") as insights_store,
    ):
        result = generate_and_store_insights(VIDEO_ID, client=client)

    assert result.problems == (INSIGHT_GENERATION_FAILED,)
    insights_store.return_value.upsert.assert_not_called()


def test_storage_exceptions_are_the_same_stage_problem() -> None:
    generated = GeneratedVideoInsights(
        summary="Summary",
        takeaways=["Takeaway"],
        suggested_questions=["Question?"],
    )
    with (
        patch(
            "backend.download_pipeline.insights.PostgresChapters",
            return_value=_chapters_store(),
        ),
        patch(
            "backend.download_pipeline.insights.generate_video_insights",
            return_value=generated,
        ),
        patch("backend.download_pipeline.insights.PostgresVideoInsights") as insights_store,
    ):
        insights_store.return_value.upsert.side_effect = RuntimeError("database unavailable")
        result = generate_and_store_insights(VIDEO_ID)

    assert result.problems == (INSIGHT_GENERATION_FAILED,)
