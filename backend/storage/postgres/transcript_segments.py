"""The `transcript_segments` table: a video's speech, in the timed pieces it was heard in.

This is the database half of `backend.storage.transcript_store`, which keeps the same
segments as a JSON file under the download root. The two hold the same normalized
transcript and neither is derived from the other yet; this one is the copy that outlives
the machine, and is what a search over many videos will read.

Only the segments live here. A transcript's source, language and timing fidelity are true
of the whole of it and sit on the video row instead, so `PostgresVideoRecords` writes those
and this module writes the text and the timings. `load` therefore returns segments rather
than a `NormalizedTranscript`: rebuilding one needs both halves, and inventing a source here
to fill the gap would be worse than making the caller ask for it.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0003_transcript_segments.sql`
applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from backend.services.transcripts import TranscriptSegment

from .connection import connection

TABLE_NAME = "transcript_segments"

# The unique constraint the upsert resolves against. Must match
# `transcript_segments_video_index_unique` in the migration.
CONFLICT_COLUMNS = ("video_id", "segment_index")

UPSERT_SQL = f"""
insert into public.{TABLE_NAME}
    (video_id, segment_index, start_seconds, end_seconds, text)
values (%s::uuid, %s, %s, %s, %s)
on conflict (video_id, segment_index) do update set
    start_seconds = excluded.start_seconds,
    end_seconds = excluded.end_seconds,
    text = excluded.text
"""

logger = logging.getLogger(__name__)


class PostgresTranscriptSegments:
    """One video's transcript in the `transcript_segments` table."""

    def __init__(self, pool=None):
        self._pool = pool

    def replace(self, video_id: str, segments: Sequence[TranscriptSegment]) -> int:
        """Make this video's stored transcript exactly `segments`, and say how many that is.

        Written as an upsert followed by a trim rather than a delete followed by an insert,
        so that a re-transcription never leaves the video with no transcript at all: every
        position is overwritten in place, and only the positions the new transcript does not
        reach are removed.

        Both happen in one transaction, which is what a real driver bought: over HTTP each
        batch was its own write, and a failure between two of them left the transcript half
        replaced. Here it either all lands or none of it does.

        The trim relies on the normalizer's guarantee that indexes run from zero with no
        gaps, which is what makes "everything at or past the new length" the right thing to
        delete.
        """
        rows = [_to_values(video_id, segment) for segment in segments]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and segment_index >= %s",
                    (video_id, len(rows)),
                )
        logger.info("Stored %d transcript segments for video %s", len(rows), video_id)
        return len(rows)

    def load(self, video_id: str) -> list[TranscriptSegment]:
        """This video's transcript in order, or an empty list if it has none.

        Read in one statement. This used to page in blocks of a thousand, which was a
        response cap of the HTTP API it was read through rather than anything about the
        data; a driver streams the whole result set.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select * from public.{TABLE_NAME} "
                "where video_id = %s::uuid order by segment_index",
                (video_id,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def delete(self, video_id: str) -> None:
        """Forget this video's transcript, leaving the video itself alone."""
        with connection(self._pool) as open_connection:
            open_connection.execute(
                f"delete from public.{TABLE_NAME} where video_id = %s::uuid", (video_id,)
            )


def _to_values(video_id: str, segment: TranscriptSegment) -> tuple:
    """One segment as the parameters of `UPSERT_SQL`, in its column order."""
    return (
        video_id,
        segment.index,
        segment.start_seconds,
        segment.end_seconds,
        segment.text,
    )


def _from_row(row: dict) -> TranscriptSegment:
    return TranscriptSegment(
        index=int(row["segment_index"]),
        start_seconds=float(row["start_seconds"]),
        end_seconds=float(row["end_seconds"]),
        text=row["text"],
    )
