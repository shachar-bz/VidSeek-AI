"""The `videos` table: what is known about a video whose file is sitting in Blob Storage.

Blob Storage holds the bytes and nothing else -- a blob's name says nothing about which
page the video came from, what it is called, or whether it was transcribed. This is the
other half: one row per stored video, keyed on the blob it describes, so that a blob found
in the container can be turned back into a video and a page URL can be turned into the blob
that holds it.

The table is created by `migrations/0002_videos.sql`; this module only reads and writes
rows. A video row is what everything else in this database hangs off: `transcript_segments`
and `comments` point at one, and `memories` and `chapters` will do the same once something
produces them.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations applied.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields

from psycopg import sql

from .connection import connection, iso_text

TABLE_NAME = "videos"

# The unique constraint the upsert resolves against. Must match
# `videos_container_blob_name_unique` in the migration.
CONFLICT_COLUMNS = ("blob_container", "blob_name")

DEFAULT_LIST_LIMIT = 50

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoRecord:
    """One video's metadata, as the backend hands it to the database.

    The required fields are the ones without which the row would not be worth writing: a
    video nobody can locate in the container, or trace back to where it came from, is not a
    record of anything. Everything else is filled in by whichever part of the pipeline
    happens to know it, and stays null when nothing does.
    """

    source: str
    source_url: str
    title: str
    blob_container: str
    blob_name: str

    # The account that requested this video, or null for a video recorded before the
    # `users` table existed (0009) or by a request nothing required a signed-in account for.
    user_id: str | None = None

    source_video_id: str | None = None
    duration_seconds: float | None = None

    # What is true of the whole transcript, whose segments live in `transcript_segments`.
    # `transcript_timing_fidelity` is a `TimingFidelity` value ("word" or "caption"),
    # stored as its string so that reading a row back does not depend on the enum still
    # holding every value some earlier version wrote.
    transcript_source: str | None = None
    transcript_language: str | None = None
    transcript_timing_fidelity: str | None = None

    file_size_bytes: int | None = None
    content_type: str | None = None
    job_id: str | None = None

    def to_row(self) -> dict:
        """The column values to write, nulls included.

        Nulls are sent rather than omitted because this is written as an upsert: leaving a
        field out would keep whatever an earlier run put there, so a video re-downloaded
        without a transcript would still claim the old one's source.
        """
        return asdict(self)


# Every column this module writes, in one fixed order, taken from the dataclass so that a
# field added there cannot be forgotten in the statement below.
COLUMN_NAMES = tuple(field.name for field in fields(VideoRecord))


@dataclass(frozen=True)
class StoredVideoRecord:
    """One `videos` row as the database returned it."""

    id: str
    created_at: str
    updated_at: str
    video: VideoRecord

    @classmethod
    def from_row(cls, row: dict) -> StoredVideoRecord:
        """Read one row back, ignoring any column this code does not know about.

        A column added to the table by a later migration should not break a backend that
        has not been updated for it yet.
        """
        return cls(
            id=str(row["id"]),
            created_at=iso_text(row["created_at"]),
            updated_at=iso_text(row["updated_at"]),
            video=VideoRecord(**{name: row.get(name) for name in COLUMN_NAMES}),
        )


def upsert_statement() -> sql.Composed:
    """`insert ... on conflict do update`, built from the dataclass's own columns.

    The conflict columns are left out of the assignment list: they are what matched, so
    setting them to the values that matched them says nothing.
    """
    updatable = [name for name in COLUMN_NAMES if name not in CONFLICT_COLUMNS]
    return sql.SQL(
        "insert into public.{table} ({columns}) values ({placeholders}) "
        "on conflict ({conflict}) do update set {assignments} returning *"
    ).format(
        table=sql.Identifier(TABLE_NAME),
        columns=sql.SQL(", ").join(sql.Identifier(name) for name in COLUMN_NAMES),
        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in COLUMN_NAMES),
        conflict=sql.SQL(", ").join(sql.Identifier(name) for name in CONFLICT_COLUMNS),
        assignments=sql.SQL(", ").join(
            sql.SQL("{column} = excluded.{column}").format(column=sql.Identifier(name))
            for name in updatable
        ),
    )


class PostgresVideoRecords:
    """The `videos` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        # Nothing here needs a setting of its own: the table name is fixed and the database
        # is baked into the pool. `pool` is accepted only so a caller can point one instance
        # at a second database without touching the shared pool.
        self._pool = pool

    def upsert(self, record: VideoRecord) -> StoredVideoRecord:
        """Record a video, replacing the row for the same container and blob name.

        Replacing rather than appending matches how the container already behaves: a second
        run of the same job overwrites the blob under that name, so a second row would
        describe a file that no longer exists.
        """
        row = record.to_row()
        values = [row[name] for name in COLUMN_NAMES]
        with connection(self._pool) as open_connection:
            written = open_connection.execute(upsert_statement(), values).fetchone()
        if written is None:
            raise RuntimeError(
                f"The {TABLE_NAME} upsert for {record.blob_name} was accepted "
                "but returned no row"
            )
        stored = StoredVideoRecord.from_row(written)
        logger.info("Recorded %s in PostgreSQL as %s", record.blob_name, stored.id)
        return stored

    def get_by_blob_name(self, container: str, blob_name: str) -> StoredVideoRecord | None:
        """The video stored as one blob, or None if nothing describes it."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where blob_container = %s and blob_name = %s limit 1",
                (container, blob_name),
            ).fetchone()
        return StoredVideoRecord.from_row(row) if row else None

    def get_by_id(self, video_id: str) -> StoredVideoRecord | None:
        """The video with this id, or None if nothing describes it."""
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select * from public.{TABLE_NAME} where id = %s::uuid", (video_id,)
            ).fetchone()
        return StoredVideoRecord.from_row(row) if row else None

    def find_by_source_url(self, source_url: str) -> list[StoredVideoRecord]:
        """Every video taken from one page, newest first.

        A list rather than a single row: the same page can be downloaded again after its
        video changes, and both uploads are real blobs in the container.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where source_url = %s order by created_at desc",
                (source_url,),
            ).fetchall()
        return [StoredVideoRecord.from_row(row) for row in rows]

    def recent(self, limit: int = DEFAULT_LIST_LIMIT) -> list[StoredVideoRecord]:
        """The most recently recorded videos, newest first."""
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} order by created_at desc limit %s",
                (limit,),
            ).fetchall()
        return [StoredVideoRecord.from_row(row) for row in rows]

    def delete(self, video_id: str) -> None:
        """Forget a video. This removes the row only; the blob is left alone.

        Deleting the two together belongs to whatever decides a video should go away, not
        here: dropping a row is cheap and reversible, and dropping the blob is neither.
        Every child row goes with it, which the foreign keys handle.
        """
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where id = %s::uuid", (video_id,)
            )
