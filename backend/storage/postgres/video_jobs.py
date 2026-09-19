"""The `video_jobs` table: what the companion is doing to one video, on a row anything can read.

The table is created by `migrations/0018_video_jobs.sql`; this module only reads and writes
rows. It is deliberately a mirror of `VideoJobResponse` (`backend/schemas/video_jobs.py`)
rather than a second vocabulary, so the website and the extension describe the same job the
same way, and neither has to translate.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields

from psycopg import sql

from .connection import connection, iso_text

TABLE_NAME = "video_jobs"

# The columns an upsert may change once a job's row already exists. `page_url`, `page_title`,
# `user_id` and `acquisition_mode` describe what the job was asked to do and who asked for
# it, fixed at creation; only what the job reports about its own progress is ever rewritten.
UPDATABLE_COLUMNS = ("status", "phase", "progress", "message", "error_code", "video_id")

DEFAULT_LIST_LIMIT = 100

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoJob:
    """One video job's row, as the companion hands it to the database while it works."""

    id: str
    page_url: str
    page_title: str
    status: str
    phase: str
    progress: float = 0.0
    message: str = ""
    user_id: str | None = None
    video_id: str | None = None
    acquisition_mode: str | None = None
    error_code: str | None = None

    def to_row(self) -> dict:
        return asdict(self)


# Every column this module writes, in one fixed order, taken from the dataclass so that a
# field added there cannot be forgotten in the statement below.
COLUMN_NAMES = tuple(field.name for field in fields(VideoJob))


@dataclass(frozen=True)
class StoredVideoJob:
    """One `video_jobs` row as the database returned it."""

    created_at: str
    updated_at: str
    job: VideoJob

    @classmethod
    def from_row(cls, row: dict) -> StoredVideoJob:
        """Read one row back, ignoring any column this code does not know about.

        A column added to the table by a later migration should not break a backend that has
        not been updated for it yet.
        """
        return cls(
            created_at=iso_text(row["created_at"]),
            updated_at=iso_text(row["updated_at"]),
            job=VideoJob(**{name: row.get(name) for name in COLUMN_NAMES}),
        )


def upsert_statement() -> sql.Composed:
    """`insert ... on conflict do update`, built from the dataclass's own columns.

    Only `UPDATABLE_COLUMNS` are reassigned on conflict: the rest are what identified and
    started the job, and rewriting them from a later progress report would let a stale retry
    overwrite who the job belongs to.
    """
    return sql.SQL(
        "insert into public.{table} ({columns}) values ({placeholders}) "
        "on conflict (id) do update set {assignments} returning *"
    ).format(
        table=sql.Identifier(TABLE_NAME),
        columns=sql.SQL(", ").join(sql.Identifier(name) for name in COLUMN_NAMES),
        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in COLUMN_NAMES),
        assignments=sql.SQL(", ").join(
            sql.SQL("{column} = excluded.{column}").format(column=sql.Identifier(name))
            for name in UPDATABLE_COLUMNS
        ),
    )


class PostgresVideoJobs:
    """The `video_jobs` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def upsert(self, job: VideoJob) -> StoredVideoJob:
        """Record a job's row, creating it on first write and updating its progress after.

        `id` is text rather than uuid because the companion generates it as `uuid4().hex`
        (`migrations/0018_video_jobs.sql`), so no cast is needed here or anywhere this id is
        compared against `videos.job_id`.
        """
        row = job.to_row()
        values = [row[name] for name in COLUMN_NAMES]
        with connection(self._pool) as open_connection:
            written = open_connection.execute(upsert_statement(), values).fetchone()
        if written is None:
            raise RuntimeError(f"The {TABLE_NAME} upsert for {job.id} returned no row")
        stored = StoredVideoJob.from_row(written)
        logger.info("Recorded job %s as %s/%s", job.id, stored.job.status, stored.job.phase)
        return stored

    def get(self, job_id: str, user_id: str) -> StoredVideoJob | None:
        """This account's job, or None if it does not exist or belongs to someone else.

        Scoped to `user_id` so that one account can never poll a job it did not start by
        guessing another account's job id.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where id = %s and user_id = %s::uuid",
                (job_id, user_id),
            ).fetchone()
        return StoredVideoJob.from_row(row) if row else None

    def list_for_user(self, user_id: str, limit: int = DEFAULT_LIST_LIMIT) -> list[StoredVideoJob]:
        """This account's jobs, newest first. What the library's live processing rows read."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} where user_id = %s::uuid "
                "order by created_at desc limit %s",
                (user_id, limit),
            ).fetchall()
        return [StoredVideoJob.from_row(row) for row in rows]

    def delete(self, job_id: str) -> None:
        """Forget a job's row. A finished job is not otherwise evicted, so this is that eviction."""
        with connection(self._pool) as open_connection:
            open_connection.execute(f"delete from public.{TABLE_NAME} where id = %s", (job_id,))
