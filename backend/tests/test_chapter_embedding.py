"""Tests for backend.services.embeddings.chapter_embedding."""

from backend.services.embeddings.chapter_embedding import build_embedding_text
from backend.services.embeddings.chapter_embedding.pipeline import embed_chapters_for_video
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def test_a_chapter_is_rendered_as_its_title_then_its_summary() -> None:
    text = build_embedding_text("Getting started", "The host explains the setup.")

    assert text == "chapter title: Getting started\nchapter summary: The host explains the setup."


def test_embed_chapters_for_video_embeds_each_chapter_and_stores_the_result(monkeypatch) -> None:
    rows = [
        {
            "chapter_id": "aaaaaaaa-1111-1111-1111-111111111111",
            "video_id": VIDEO_ID,
            "title": "Getting started",
            "summary": "The host explains the setup.",
            "start_seconds": 0.0,
            "end_seconds": 30.0,
        }
    ]
    pool = FakePool(rows=rows)

    embedded_texts = []

    def fake_embed_passages(texts: list[str]) -> list[list[float]]:
        embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(
        "backend.services.embeddings.chapter_embedding.pipeline.embed_passages", fake_embed_passages
    )

    written = embed_chapters_for_video(VIDEO_ID, pool=pool)

    assert written == 1
    assert embedded_texts == [
        "chapter title: Getting started\nchapter summary: The host explains the setup."
    ]
    # recorded[0] is the `chapters_for_video` select; the upsert is recorded[1].
    stored = pool.recorded[1].parameters[0]
    assert stored[0] == rows[0]["chapter_id"]
    assert stored[4] == [0.1, 0.2, 0.3]
    assert stored[5] == "intfloat/multilingual-e5-small"
    assert stored[6] == 3


def test_embed_chapters_for_video_with_no_chapters_clears_stale_embeddings() -> None:
    pool = FakePool(rows=[])
    written = embed_chapters_for_video(VIDEO_ID, pool=pool)

    assert written == 0
