"""Re-runs stage four for every video whose vectors an older embedding model wrote.

Memory search only compares vectors from the model the query is embedded with, so a video
embedded before the switch to multilingual-e5-small is unsearchable until it is embedded
again. Everything the vectors are built from is already in the database, which is what
makes this a loop over `embed_video` and nothing more.

    python -m backend.download_pipeline.reembed_stale_videos

Needs AZURE_DATABASE_URL in `backend/.env`.
"""

from __future__ import annotations

import logging

from backend.services.embeddings.multilingual_text_embedding import MODEL_NAME
from backend.storage.postgres import PostgresChapterEmbeddings, PostgresMemoryEmbeddings

from .embedding import embed_video

logger = logging.getLogger(__name__)


def stale_video_ids(*, pool=None) -> list[str]:
    """Every video holding memory or chapter vectors from a model other than the current one."""
    memory_videos = PostgresMemoryEmbeddings(pool=pool).video_ids_embedded_with_other_models(MODEL_NAME)
    chapter_videos = PostgresChapterEmbeddings(pool=pool).video_ids_embedded_with_other_models(MODEL_NAME)
    return sorted(set(memory_videos) | set(chapter_videos))


def reembed_stale_videos(*, pool=None) -> tuple[int, int]:
    """Re-embed every stale video, and return how many succeeded and how many failed."""
    video_ids = stale_video_ids(pool=pool)
    logger.info("%d videos hold vectors from a model other than %s", len(video_ids), MODEL_NAME)
    succeeded = failed = 0
    for video_id in video_ids:
        if embed_video(video_id, pool=pool).problems:
            failed += 1
        else:
            succeeded += 1
    return succeeded, failed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    succeeded, failed = reembed_stale_videos()
    logger.info("Re-embedded %d videos, %d failed", succeeded, failed)
