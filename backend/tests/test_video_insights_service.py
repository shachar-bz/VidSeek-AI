"""Tests generated insights use validated Structured Outputs and summary-only input."""

from unittest.mock import patch

import pytest

from backend.services.video_insights import (
    API_KEY_NAME,
    MODEL,
    GeneratedVideoInsights,
    InsightChapter,
    InsightGenerationError,
    build_client,
    generate_video_insights,
)


class _FakeResponse:
    def __init__(self, parsed, status="completed"):
        self.output_parsed = parsed
        self.status = status


class _FakeResponses:
    def __init__(self, parsed, status="completed"):
        self._parsed = parsed
        self._status = status
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._parsed, self._status)


class _FakeClient:
    def __init__(self, parsed, status="completed"):
        self.responses = _FakeResponses(parsed, status)


CHAPTERS = [
    InsightChapter(
        title="Testing safely",
        summary="The chapter explains test isolation.",
        memory_summaries=(
            "Dependencies are replaced with fakes.",
            "Assertions focus on public behavior.",
        ),
    )
]

VALID = GeneratedVideoInsights(
    summary="A practical guide to isolated tests.",
    takeaways=["Replace external dependencies", "Assert observable behavior"],
    suggested_questions=["How do fakes keep tests deterministic?"],
)


def test_client_uses_the_project_key_and_retry_configuration() -> None:
    with (
        patch("backend.services.video_insights.config.require", return_value="secret") as require,
        patch("backend.services.video_insights.OpenAI") as openai,
    ):
        client = build_client(max_retries=7)

    require.assert_called_once_with(API_KEY_NAME)
    openai.assert_called_once_with(api_key="secret", max_retries=7)
    assert client is openai.return_value


def test_generation_uses_the_required_model_and_structured_output_type() -> None:
    client = _FakeClient(VALID)

    result = generate_video_insights(CHAPTERS, client=client)

    assert result == VALID
    call = client.responses.calls[0]
    assert call["model"] == MODEL == "gpt-5.6-terra"
    assert call["text_format"] is GeneratedVideoInsights
    assert "overall summary" in call["instructions"]


def test_input_contains_chapter_and_memory_summaries_but_no_transcript() -> None:
    client = _FakeClient(VALID)

    generate_video_insights(CHAPTERS, client=client)

    sent = client.responses.calls[0]["input"]
    assert "Testing safely" in sent
    assert "The chapter explains test isolation." in sent
    assert "Dependencies are replaced with fakes." in sent
    assert "Assertions focus on public behavior." in sent
    assert "raw transcript words" not in sent


def test_absent_structured_output_is_rejected() -> None:
    with pytest.raises(InsightGenerationError, match="no parsed insights"):
        generate_video_insights(CHAPTERS, client=_FakeClient(None, status="incomplete"))


def test_parsed_output_is_revalidated_before_it_is_returned() -> None:
    invalid = GeneratedVideoInsights.model_construct(
        summary=" ",
        takeaways=["one", "two", "three", "four", "five", "six"],
        suggested_questions=["Question?"],
    )

    with pytest.raises(InsightGenerationError, match="invalid video insights"):
        generate_video_insights(CHAPTERS, client=_FakeClient(invalid))


@pytest.mark.parametrize(
    "field",
    [
        {"summary": "Summary", "takeaways": ["x"] * 6, "suggested_questions": ["q"]},
        {"summary": "Summary", "takeaways": ["x"], "suggested_questions": ["q"] * 4},
    ],
)
def test_structured_schema_caps_takeaways_and_questions(field: dict) -> None:
    with pytest.raises(ValueError):
        GeneratedVideoInsights(**field)
