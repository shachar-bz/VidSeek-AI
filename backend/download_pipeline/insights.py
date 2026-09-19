"""Stage five: generate and store a video's summary, takeaways and starter questions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import OpenAI

from backend.services.video_insights import MODEL, InsightChapter, generate_video_insights
from backend.storage.postgres import NewVideoInsights, PostgresChapters, PostgresVideoInsights

from .result import INSIGHT_GENERATION_FAILED

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InsightGenerationOutcome:
    """Whether this run stored insights and any problem that prevented it."""

    stored: bool = False
    problems: tuple[str, ...] = field(default_factory=tuple)


def generate_and_store_insights(
    video_id: str,
    *,
    pool=None,
    client: OpenAI | None = None,
) -> InsightGenerationOutcome:
    """Generate insights from durable summaries and store them without risking the video."""
    try:
        chapters_store = PostgresChapters(pool=pool)
        chapters = []
        for outline_entry in chapters_store.video_outline(video_id):
            chapter = chapters_store.chapter_with_memories(
                video_id, outline_entry.chapter_id
            )
            if chapter is None:
                raise RuntimeError(
                    f"Chapter {outline_entry.chapter_id} disappeared while loading "
                    f"video {video_id}"
                )
            chapters.append(
                InsightChapter(
                    title=chapter.title,
                    summary=chapter.summary,
                    memory_summaries=tuple(memory.summary for memory in chapter.memories),
                )
            )

        generated = generate_video_insights(chapters, client=client)
        PostgresVideoInsights(pool=pool).upsert(
            NewVideoInsights(
                video_id=video_id,
                summary=generated.summary,
                takeaways=generated.takeaways,
                suggested_questions=generated.suggested_questions,
                model=MODEL,
            )
        )
    except Exception:
        logger.exception("Generating insights for video %s failed", video_id)
        return InsightGenerationOutcome(problems=(INSIGHT_GENERATION_FAILED,))

    return InsightGenerationOutcome(stored=True)
