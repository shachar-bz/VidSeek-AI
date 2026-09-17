"""Embeds a video's chapters and stores the vectors in `chapter_embeddings`.

Reads each chapter from PostgreSQL (`chapters`), embeds `text.build_embedding_text`'s
rendering of it with the shared model, and writes the result back, keyed on the chapter.
`PostgresChapterEmbeddings.replace` is what makes this safe to run again after chapters
change: it overwrites every chapter's vector in place and drops any the run no longer
produced.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations up to
`0011_chapter_embeddings_video_times.sql` applied.
"""

from __future__ import annotations

import logging

from backend.services.embeddings.model import MODEL_NAME, embed_text
from backend.storage.postgres import ChapterEmbedding, PostgresChapterEmbeddings

from .text import build_embedding_text

logger = logging.getLogger(__name__)


def embed_chapters_for_video(video_id: str, *, pool=None) -> int:
    """Embed and store every chapter of one video, and return how many were written."""
    store = PostgresChapterEmbeddings(pool=pool)
    chapters = store.chapters_for_video(video_id)

    embeddings = []
    for chapter in chapters:
        text = build_embedding_text(chapter.title, chapter.summary)
        vector = embed_text(text)
        embeddings.append(
            ChapterEmbedding(
                chapter_id=chapter.chapter_id,
                start_seconds=chapter.start_seconds,
                end_seconds=chapter.end_seconds,
                embedding=vector,
                model=MODEL_NAME,
                dimensions=len(vector),
            )
        )

    written = store.replace(video_id, embeddings)
    logger.info("Embedded %d chapters for video %s", written, video_id)
    return written
