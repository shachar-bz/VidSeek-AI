"""Tests for the `transcript_segments` table a video's transcript is stored in."""

from backend.services.transcripts import TranscriptSegment
from backend.storage.supabase import SupabaseTranscriptSegments
from backend.storage.supabase.transcript_segments import (
    CONFLICT_TARGET,
    READ_PAGE_ROWS,
    TABLE_NAME,
    WRITE_BATCH_ROWS,
)

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def _segments(count: int, *, start_index: int = 0) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            index=index,
            start_seconds=float(index),
            end_seconds=float(index) + 0.5,
            text=f"segment {index}",
        )
        for index in range(start_index, start_index + count)
    ]


def _row(segment: TranscriptSegment) -> dict:
    return {
        "id": f"row-{segment.index}",
        "video_id": VIDEO_ID,
        "segment_index": segment.index,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "text": segment.text,
        "created_at": "2026-09-14T10:00:00+00:00",
    }


class FakeTable:
    """Records every query built against it, and serves reads out of `rows` by range."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple] = []
        self._range: tuple[int, int] | None = None
        self._is_read = False

    def _record(self, *call):
        self.calls.append(call)
        return self

    def upsert(self, rows, on_conflict=None):
        return self._record("upsert", rows, on_conflict)

    def select(self, columns):
        self._is_read = True
        return self._record("select", columns)

    def delete(self):
        return self._record("delete")

    def eq(self, column, value):
        return self._record("eq", column, value)

    def gte(self, column, value):
        return self._record("gte", column, value)

    def order(self, column, desc=False):
        return self._record("order", column, desc)

    def range(self, start, end):
        self._range = (start, end)
        return self._record("range", start, end)

    def execute(self):
        if not self._is_read:
            return FakeResponse([])
        start, end = self._range or (0, len(self.rows) - 1)
        return FakeResponse(self.rows[start : end + 1])


class FakeResponse:
    def __init__(self, data: list[dict]):
        self.data = data


class FakeSupabaseClient:
    def __init__(self, rows: list[dict] | None = None):
        self.table_stub = FakeTable(rows or [])

    def table(self, name: str) -> FakeTable:
        assert name == TABLE_NAME
        return self.table_stub


def _store(rows: list[dict] | None = None):
    client = FakeSupabaseClient(rows)
    return SupabaseTranscriptSegments(client=client), client.table_stub


def _calls_named(table: FakeTable, name: str) -> list[tuple]:
    return [call for call in table.calls if call[0] == name]


def test_a_transcript_is_written_as_one_row_per_timed_segment() -> None:
    store, table = _store()
    written = store.replace(VIDEO_ID, _segments(3))

    assert written == 3
    upserted = _calls_named(table, "upsert")[0][1]
    assert upserted[0] == {
        "video_id": VIDEO_ID,
        "segment_index": 0,
        "start_seconds": 0.0,
        "end_seconds": 0.5,
        "text": "segment 0",
    }
    assert [row["segment_index"] for row in upserted] == [0, 1, 2]


def test_a_rewrite_overwrites_each_position_rather_than_emptying_the_video_first() -> None:
    # A delete-then-insert leaves a window in which the video has no transcript at all,
    # and a failure inside that window leaves it there.
    store, table = _store()
    store.replace(VIDEO_ID, _segments(3))

    kinds = [call[0] for call in table.calls]
    assert kinds.index("upsert") < kinds.index("delete")
    assert _calls_named(table, "upsert")[0][2] == CONFLICT_TARGET


def test_a_shorter_transcript_takes_the_old_tail_with_it() -> None:
    # The normalizer numbers segments from zero with no gaps, so everything at or past the
    # new length belongs to the transcript being replaced.
    store, table = _store()
    store.replace(VIDEO_ID, _segments(3))

    assert ("gte", "segment_index", 3) in table.calls


def test_replacing_a_transcript_with_nothing_clears_it() -> None:
    store, table = _store()

    assert store.replace(VIDEO_ID, []) == 0
    assert _calls_named(table, "upsert") == []
    assert ("gte", "segment_index", 0) in table.calls


def test_a_transcript_too_long_for_one_request_is_sent_in_batches() -> None:
    store, table = _store()
    store.replace(VIDEO_ID, _segments(WRITE_BATCH_ROWS + 1))

    batches = _calls_named(table, "upsert")
    assert [len(call[1]) for call in batches] == [WRITE_BATCH_ROWS, 1]


def test_a_transcript_is_read_back_in_order() -> None:
    store, table = _store([_row(segment) for segment in _segments(3)])
    loaded = store.load(VIDEO_ID)

    assert loaded == _segments(3)
    assert ("order", "segment_index", False) in table.calls
    assert ("eq", "video_id", VIDEO_ID) in table.calls


def test_a_transcript_longer_than_one_response_is_paged_until_it_runs_out() -> None:
    # PostgREST caps how much it returns, so asking once would silently truncate an hour
    # of speech to whatever the first page held.
    store, table = _store([_row(segment) for segment in _segments(READ_PAGE_ROWS + 5)])
    loaded = store.load(VIDEO_ID)

    assert len(loaded) == READ_PAGE_ROWS + 5
    assert loaded[-1].index == READ_PAGE_ROWS + 4
    assert len(_calls_named(table, "range")) == 2


def test_a_transcript_that_exactly_fills_a_page_still_asks_for_the_next_one() -> None:
    store, table = _store([_row(segment) for segment in _segments(READ_PAGE_ROWS)])
    loaded = store.load(VIDEO_ID)

    assert len(loaded) == READ_PAGE_ROWS
    assert len(_calls_named(table, "range")) == 2


def test_a_video_with_no_transcript_reads_back_as_no_segments() -> None:
    store, _ = _store([])

    assert store.load(VIDEO_ID) == []


def test_deleting_a_transcript_names_only_the_video_it_belongs_to() -> None:
    store, table = _store()
    store.delete(VIDEO_ID)

    assert ("delete",) in table.calls
    assert ("eq", "video_id", VIDEO_ID) in table.calls
