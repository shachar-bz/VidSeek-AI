"""The `videos` table: what is known about a video whose file is sitting in R2.

R2 holds the bytes and nothing else — an object key says nothing about which page the
video came from, what it is called, or whether it was transcribed. This is the other half:
one row per stored video, keyed on the R2 object it describes, so that a key found in the
bucket can be turned back into a video and a page URL can be turned into the key that
holds it.

The table is created by `migrations/0001_videos.sql`, which is applied by hand once; this
module only reads and writes rows. A video row is also what everything else in this
database hangs off: `transcript_segments` already points at one, and `chapters` and
`memories` will do the same once there is something producing them.

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) in `backend/.env`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields

from .client import build_client, shared_client
from .settings import SupabaseSettings

TABLE_NAME = "videos"

# The unique constraint an upsert resolves against, spelled the way PostgREST expects it.
# It must match `videos_bucket_object_key_unique` in the migration: PostgREST reports a
# mismatch as a plain constraint violation, which reads like a duplicate row rather than
# like the configuration error it is.
CONFLICT_TARGET = "r2_bucket,r2_object_key"

DEFAULT_LIST_LIMIT = 50

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoRecord:
    """One video's metadata, as the backend hands it to Supabase.

    The required fields are the ones without which the row would not be worth writing: a
    video nobody can locate in the bucket, or trace back to where it came from, is not a
    record of anything. Everything else is filled in by whichever part of the pipeline
    happens to know it, and stays null when nothing does.
    """

    source: str
    source_url: str
    title: str
    r2_bucket: str
    r2_object_key: str
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


@dataclass(frozen=True)
class StoredVideoRecord:
    """One `videos` row as Supabase returned it."""

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
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            video=VideoRecord(
                **{field.name: row.get(field.name) for field in fields(VideoRecord)}
            ),
        )


class SupabaseVideoRecords:
    """The `videos` table, as the rest of the backend sees it."""

    def __init__(self, client=None, settings: SupabaseSettings | None = None):
        # Unlike the R2 storage, nothing here needs a setting of its own: the table name
        # is fixed and the project is baked into the client. `settings` is accepted only
        # so a caller can point one instance at a second project without touching the
        # shared client.
        self._client = client if client is not None else _client_for(settings)

    def upsert(self, record: VideoRecord) -> StoredVideoRecord:
        """Record a video, replacing the row for the same bucket and object key.

        Replacing rather than appending matches how the bucket already behaves: a second
        run of the same job overwrites the object under that key, so a second row would
        describe a file that no longer exists.
        """
        response = (
            self._client.table(TABLE_NAME)
            .upsert(record.to_row(), on_conflict=CONFLICT_TARGET)
            .execute()
        )
        stored = _one(response)
        if stored is None:
            raise RuntimeError(
                f"Supabase accepted the {TABLE_NAME} upsert for "
                f"{record.r2_object_key} but returned no row"
            )
        logger.info("Recorded %s in Supabase as %s", record.r2_object_key, stored.id)
        return stored

    def get_by_object_key(self, bucket: str, object_key: str) -> StoredVideoRecord | None:
        """The video stored under one R2 object, or None if nothing describes it."""
        response = (
            self._client.table(TABLE_NAME)
            .select("*")
            .eq("r2_bucket", bucket)
            .eq("r2_object_key", object_key)
            .limit(1)
            .execute()
        )
        return _one(response)

    def find_by_source_url(self, source_url: str) -> list[StoredVideoRecord]:
        """Every video taken from one page, newest first.

        A list rather than a single row: the same page can be downloaded again after its
        video changes, and both uploads are real objects in the bucket.
        """
        response = (
            self._client.table(TABLE_NAME)
            .select("*")
            .eq("source_url", source_url)
            .order("created_at", desc=True)
            .execute()
        )
        return _all(response)

    def recent(self, limit: int = DEFAULT_LIST_LIMIT) -> list[StoredVideoRecord]:
        """The most recently recorded videos, newest first."""
        response = (
            self._client.table(TABLE_NAME)
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return _all(response)

    def delete(self, video_id: str) -> None:
        """Forget a video. This removes the row only; the R2 object is left alone.

        Deleting the two together belongs to whatever decides a video should go away, not
        here: dropping a row is cheap and reversible, and dropping the object is neither.
        """
        self._client.table(TABLE_NAME).delete().eq("id", video_id).execute()


def _client_for(settings: SupabaseSettings | None):
    return shared_client() if settings is None else build_client(settings)


def _all(response) -> list[StoredVideoRecord]:
    return [StoredVideoRecord.from_row(row) for row in (response.data or [])]


def _one(response) -> StoredVideoRecord | None:
    rows = _all(response)
    return rows[0] if rows else None
