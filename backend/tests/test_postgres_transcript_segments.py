"""Tests for the `transcript_segments` table one video's timed speech is written to."""

from backend.services.transcripts import TranscriptSegment
from backend.storage.postgres import PostgresTranscriptSegments
from backend.storage.postgres.transcript_segments import TABLE_NAME
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

SEGMENTS = [
    TranscriptSegment(index=0, start_seconds=0.0, end_seconds=1.5, text="שלום"),
    TranscriptSegment(index=1, start_seconds=1.5, end_seconds=3.0, text="and welcome"),
]


def _rows(count: int) -> list[dict]:
    return [
        {
            "video_id": VIDEO_ID,
            "segment_index": index,
            "start_seconds": float(index),
            "end_seconds": float(index) + 1.0,
            "text": f"segment {index}",
        }
        for index in range(count)
    ]


def _segments(rows: list[dict] | None = None) -> tuple[PostgresTranscriptSegments, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresTranscriptSegments(pool=pool), pool


def test_a_transcript_is_written_as_one_statement_per_batch_not_per_segment() -> None:
    segments, pool = _segments()
    written = segments.replace(VIDEO_ID, SEGMENTS)

    assert written == len(SEGMENTS)
    assert pool.recorded[0].many is True
    assert len(pool.recorded[0].parameters) == len(SEGMENTS)


def test_every_segment_carries_the_timings_the_transcript_measured() -> None:
    segments, pool = _segments()
    segments.replace(VIDEO_ID, SEGMENTS)

    assert pool.recorded[0].parameters == [
        (VIDEO_ID, 0, 0.0, 1.5, "שלום"),
        (VIDEO_ID, 1, 1.5, 3.0, "and welcome"),
    ]


def test_a_position_that_already_exists_is_overwritten_rather_than_duplicated() -> None:
    # The upsert is what lets a re-transcription replace a video's segments in place
    # instead of leaving the old ones interleaved with the new.
    segments, pool = _segments()
    segments.replace(VIDEO_ID, SEGMENTS)

    assert "on conflict (video_id, segment_index) do update set" in pool.statements[0]


def test_a_shorter_retranscription_leaves_no_tail_behind() -> None:
    segments, pool = _segments()
    segments.replace(VIDEO_ID, SEGMENTS)

    assert "segment_index >= %s" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, len(SEGMENTS))


def test_an_empty_transcript_deletes_what_was_there_without_writing_anything() -> None:
    # `executemany` with no rows is a statement that says nothing; the trim is the whole
    # of the work, and it removes everything from index zero onwards.
    segments, pool = _segments()
    written = segments.replace(VIDEO_ID, [])

    assert written == 0
    assert not any(item.many for item in pool.recorded)
    assert pool.recorded[-1].parameters == (VIDEO_ID, 0)


def test_the_write_and_the_trim_are_one_transaction() -> None:
    # Two transactions would leave a window in which the old tail is gone and the new
    # segments are not there yet, which is a transcript nobody wrote.
    segments, pool = _segments()
    segments.replace(VIDEO_ID, SEGMENTS)

    assert pool.transactions == 1


def test_a_transcript_comes_back_in_the_order_it_was_spoken() -> None:
    segments, pool = _segments(_rows(3))
    loaded = segments.load(VIDEO_ID)

    assert [segment.index for segment in loaded] == [0, 1, 2]
    assert "order by segment_index" in pool.statements[0]


def test_a_long_transcript_is_read_in_one_statement() -> None:
    # This used to be paged a thousand rows at a time, which was a cap of the HTTP API it
    # was read through rather than anything about the data.
    segments, pool = _segments(_rows(2500))
    loaded = segments.load(VIDEO_ID)

    assert len(loaded) == 2500
    assert len(pool.statements) == 1


def test_a_video_with_no_transcript_is_an_empty_list_rather_than_an_error() -> None:
    segments, _ = _segments([])

    assert segments.load(VIDEO_ID) == []


def test_deleting_a_transcript_is_scoped_to_one_video() -> None:
    segments, pool = _segments()
    segments.delete(VIDEO_ID)

    assert pool.statements[0] == (
        f"delete from public.{TABLE_NAME} where video_id = %s::uuid"
    )
    assert pool.recorded[0].parameters == (VIDEO_ID,)


def test_the_video_id_is_bound_as_a_uuid_rather_than_as_text() -> None:
    # `video_id` is a uuid column and the store passes a Python string, which Postgres
    # will not coerce on its own.
    segments, pool = _segments()
    segments.replace(VIDEO_ID, SEGMENTS)

    assert "%s::uuid" in pool.statements[0]
    assert "%s::uuid" in pool.statements[-1]


def test_speech_is_read_by_time_as_the_segments_overlapping_the_window() -> None:
    segments, pool = _segments(_rows(2))
    loaded = segments.overlapping(VIDEO_ID, 12.0, 30.0)

    assert [segment.index for segment in loaded] == [0, 1]
    statement = pool.statements[0]
    assert "start_seconds < %s and end_seconds > %s" in statement
    assert "order by segment_index" in statement
    # The window's end bounds the segment's start, and its start the segment's end.
    assert pool.recorded[0].parameters == (VIDEO_ID, 30.0, 12.0)
