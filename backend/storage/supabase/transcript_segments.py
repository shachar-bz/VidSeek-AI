"""The `transcript_segments` table: a video's speech, in the timed pieces it was heard in.

This is the database half of `backend.storage.transcript_store`, which keeps the same
segments as a JSON file under the download root. The two hold the same normalized
transcript and neither is derived from the other yet; this one is the copy that outlives
the machine, and is what a search over many videos will read.

Only the segments live here. A transcript's source, language and timing fidelity are true
of the whole of it and sit on the video row instead, so `SupabaseVideoRecords` writes
those and this module writes the text and the timings. `load` therefore returns segments
rather than a `NormalizedTranscript`: rebuilding one needs both halves, and inventing a
source here to fill the gap would be worse than making the caller ask for it.

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) in `backend/.env`,
and `migrations/0002_transcript_segments.sql` applied to the project.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

from backend.services.transcripts import TranscriptSegment

from .client import build_client, shared_client
from .settings import SupabaseSettings

TABLE_NAME = "transcript_segments"

# The unique constraint an upsert resolves against. Must match
# `transcript_segments_video_index_unique` in the migration.
CONFLICT_TARGET = "video_id,segment_index"

# How many segments go in one request. An hour of speech is a few thousand segments, which
# is far too much for one URL-length-limited call but only a handful of round trips at
# this size.
WRITE_BATCH_ROWS = 500

# How many segments come back in one read. PostgREST caps a response at its own configured
# maximum, so a long transcript has to be paged rather than asked for in full.
READ_PAGE_ROWS = 1000

logger = logging.getLogger(__name__)


class SupabaseTranscriptSegments:
    """One video's transcript in the `transcript_segments` table."""

    def __init__(self, client=None, settings: SupabaseSettings | None = None):
        self._client = (
            client
            if client is not None
            else (shared_client() if settings is None else build_client(settings))
        )

    def replace(self, video_id: str, segments: Sequence[TranscriptSegment]) -> int:
        """Make this video's stored transcript exactly `segments`, and say how many that is.

        Written as an upsert followed by a trim rather than a delete followed by an
        insert, so that a re-transcription never leaves the video with no transcript at
        all: every position is overwritten in place, and only the positions the new
        transcript does not reach are removed.

        The trim relies on the normalizer's guarantee that indexes run from zero with no
        gaps, which is what makes "everything at or past the new length" the right thing
        to delete.
        """
        rows = [_to_row(video_id, segment) for segment in segments]
        for batch in _batched(rows, WRITE_BATCH_ROWS):
            self._client.table(TABLE_NAME).upsert(batch, on_conflict=CONFLICT_TARGET).execute()
        self._trim_beyond(video_id, len(rows))
        logger.info("Stored %d transcript segments for video %s", len(rows), video_id)
        return len(rows)

    def load(self, video_id: str) -> list[TranscriptSegment]:
        """This video's transcript in order, or an empty list if it has none.

        Paged, because a long transcript is longer than one PostgREST response: an hour of
        speech runs to a few thousand segments.
        """
        segments: list[TranscriptSegment] = []
        while True:
            response = (
                self._client.table(TABLE_NAME)
                .select("*")
                .eq("video_id", video_id)
                .order("segment_index")
                .range(len(segments), len(segments) + READ_PAGE_ROWS - 1)
                .execute()
            )
            page = [_from_row(row) for row in (response.data or [])]
            segments.extend(page)
            if len(page) < READ_PAGE_ROWS:
                return segments

    def delete(self, video_id: str) -> None:
        """Forget this video's transcript, leaving the video itself alone."""
        self._client.table(TABLE_NAME).delete().eq("video_id", video_id).execute()

    def _trim_beyond(self, video_id: str, segment_count: int) -> None:
        """Drop the tail a shorter transcript left behind."""
        (
            self._client.table(TABLE_NAME)
            .delete()
            .eq("video_id", video_id)
            .gte("segment_index", segment_count)
            .execute()
        )


def _to_row(video_id: str, segment: TranscriptSegment) -> dict:
    return {
        "video_id": video_id,
        "segment_index": segment.index,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "text": segment.text,
    }


def _from_row(row: dict) -> TranscriptSegment:
    return TranscriptSegment(
        index=int(row["segment_index"]),
        start_seconds=float(row["start_seconds"]),
        end_seconds=float(row["end_seconds"]),
        text=row["text"],
    )


def _batched(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
