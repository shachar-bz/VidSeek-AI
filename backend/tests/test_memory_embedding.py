"""Tests for backend.services.embeddings.memory_embedding."""

from backend.services.embeddings.memory_embedding import build_embedding_text
from backend.services.embeddings.memory_embedding.pipeline import embed_memories_for_video
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def test_a_memory_in_a_chapter_is_rendered_with_its_chapter_title_first() -> None:
    text = build_embedding_text(
        "Getting started", "The host explains the setup.", "Okay, so first you plug it in."
    )

    assert text == (
        "chapter title: Getting started\n"
        "memory summary: The host explains the setup.\n"
        "memory text: Okay, so first you plug it in."
    )


def test_a_memory_with_no_chapter_yet_has_no_chapter_title_line() -> None:
    text = build_embedding_text(None, "A moment with no chapter yet.", "Some raw speech.")

    assert text == "memory summary: A moment with no chapter yet.\nmemory text: Some raw speech."


def test_embed_memories_for_video_embeds_each_memory_and_stores_the_result(monkeypatch) -> None:
    rows = [
        {
            "memory_id": "aaaaaaaa-1111-1111-1111-111111111111",
            "video_id": VIDEO_ID,
            "chapter_id": "66666666-7777-8888-9999-000000000000",
            "chapter_title": "Getting started",
            "summary": "The host explains the setup.",
            "text": "Okay, so first you plug it in.",
        }
    ]
    pool = FakePool(rows=rows)

    embedded_texts = []

    def fake_embed_passages(texts: list[str]) -> list[list[float]]:
        embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(
        "backend.services.embeddings.memory_embedding.pipeline.embed_passages", fake_embed_passages
    )

    written = embed_memories_for_video(VIDEO_ID, pool=pool)

    assert written == 1
    assert embedded_texts == [
        "chapter title: Getting started\n"
        "memory summary: The host explains the setup.\n"
        "memory text: Okay, so first you plug it in."
    ]
    # recorded[0] is memories_for_video's own read; the batch write is recorded[1].
    stored = pool.recorded[1].parameters[0]
    assert stored[0] == rows[0]["memory_id"]
    assert stored[3] == [0.1, 0.2, 0.3]
    assert stored[4] == "intfloat/multilingual-e5-small"
    assert stored[5] == 3


def test_embed_memories_for_video_with_no_memories_clears_stale_embeddings() -> None:
    pool = FakePool(rows=[])
    written = embed_memories_for_video(VIDEO_ID, pool=pool)

    assert written == 0
