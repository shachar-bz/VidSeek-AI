"""The `video_insights` table: a video's generated summary, takeaways and suggested questions.

The table is created by `migrations/0020_video_insights.sql`; this module only reads and
writes rows. One row per video, keyed on the video itself and shared by every account that
links it -- the same choice `chapters` and `memories` make, for the same reason: these are
properties of the shared video, not of any one account's library link.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .connection import connection, iso_text

TABLE_NAME = "video_insights"

UPSERT_SQL = f"""
insert into public.{TABLE_NAME} (video_id, summary, takeaways, suggested_questions, model)
values (%s::uuid, %s, %s, %s, %s)
on conflict (video_id) do update set
    summary = excluded.summary,
    takeaways = excluded.takeaways,
    suggested_questions = excluded.suggested_questions,
    model = excluded.model
returning *
"""

GET_SQL = f"select * from public.{TABLE_NAME} where video_id = %s::uuid"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewVideoInsights:
    """A video's generated insights, as the pipeline hands them to the database."""

    video_id: str
    summary: str
    takeaways: list[str]
    suggested_questions: list[str]
    model: str | None = None


@dataclass(frozen=True)
class StoredVideoInsights:
    """One `video_insights` row as the database returned it."""

    video_id: str
    summary: str
    takeaways: list[str]
    suggested_questions: list[str]
    model: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> StoredVideoInsights:
        return cls(
            video_id=str(row["video_id"]),
            summary=row["summary"],
            takeaways=list(row.get("takeaways") or []),
            suggested_questions=list(row.get("suggested_questions") or []),
            model=row.get("model"),
            created_at=iso_text(row["created_at"]),
            updated_at=iso_text(row["updated_at"]),
        )


class PostgresVideoInsights:
    """The `video_insights` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def upsert(self, insights: NewVideoInsights) -> StoredVideoInsights:
        """Record a video's generated insights, replacing any earlier generation.

        A video has one set of insights or none -- there is no separate id for this row, the
        video is the key -- so a second write, the pipeline running again, replaces the first
        rather than adding to it.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                UPSERT_SQL,
                (
                    insights.video_id,
                    insights.summary,
                    list(insights.takeaways),
                    list(insights.suggested_questions),
                    insights.model,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError(
                f"The {TABLE_NAME} upsert for video {insights.video_id} returned no row"
            )
        stored = StoredVideoInsights.from_row(row)
        logger.info("Recorded insights for video %s", insights.video_id)
        return stored

    def get(self, video_id: str) -> StoredVideoInsights | None:
        """This video's generated insights, or None if it has not reached `ready` yet."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(GET_SQL, (video_id,)).fetchone()
        return StoredVideoInsights.from_row(row) if row else None
