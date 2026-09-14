"""Tests for the `video_comments` table a YouTube video's top comments are stored in."""

from backend.services.video_download.youtube.comments import CommentEntry
from backend.storage.supabase import SupabaseVideoComments
from backend.storage.supabase.video_comments import CONFLICT_TARGET, TABLE_NAME, WRITE_BATCH_ROWS

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def _comments(count: int) -> list[CommentEntry]:
    return [
        CommentEntry(
            id=f"comment-{index}",
            author=f"author {index}",
            text=f"comment {index}",
            like_count=count - index,
            reply_count=0,
            published_at="2026-09-14T10:00:00+00:00",
        )
        for index in range(count)
    ]


def _row(comment: CommentEntry) -> dict:
    return {
        "id": comment.id,
        "video_id": VIDEO_ID,
        "author": comment.author,
        "text": comment.text,
        "like_count": comment.like_count,
        "reply_count": comment.reply_count,
        "published_at": comment.published_at,
        "created_at": "2026-09-14T10:00:00+00:00",
    }


class FakeTable:
    """Records every query built against it, and serves reads out of `rows`."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple] = []
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

    @property
    def not_(self):
        self._record("not_")
        return self

    def in_(self, column, values):
        return self._record("in_", column, values)

    def order(self, column, desc=False):
        return self._record("order", column, desc)

    def execute(self):
        if not self._is_read:
            return FakeResponse([])
        return FakeResponse(self.rows)


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
    return SupabaseVideoComments(client=client), client.table_stub


def _calls_named(table: FakeTable, name: str) -> list[tuple]:
    return [call for call in table.calls if call[0] == name]


def test_comments_are_written_as_one_row_per_comment() -> None:
    store, table = _store()
    written = store.replace(VIDEO_ID, _comments(3))

    assert written == 3
    upserted = _calls_named(table, "upsert")[0][1]
    assert upserted[0] == {
        "id": "comment-0",
        "video_id": VIDEO_ID,
        "author": "author 0",
        "text": "comment 0",
        "like_count": 3,
        "reply_count": 0,
        "published_at": "2026-09-14T10:00:00+00:00",
    }
    assert _calls_named(table, "upsert")[0][2] == CONFLICT_TARGET


def test_a_rewrite_overwrites_each_comment_rather_than_emptying_the_video_first() -> None:
    # A delete-then-insert leaves a window in which the video has no comments at all, and a
    # failure inside that window leaves it there.
    store, table = _store()
    store.replace(VIDEO_ID, _comments(3))

    kinds = [call[0] for call in table.calls]
    assert kinds.index("upsert") < kinds.index("delete")


def test_a_rewrite_drops_comments_the_new_fetch_did_not_bring_back() -> None:
    store, table = _store()
    store.replace(VIDEO_ID, _comments(3))

    assert ("in_", "id", ["comment-0", "comment-1", "comment-2"]) in table.calls
    assert _calls_named(table, "not_") != []


def test_replacing_comments_with_nothing_clears_them() -> None:
    store, table = _store()

    assert store.replace(VIDEO_ID, []) == 0
    assert _calls_named(table, "upsert") == []
    # Nothing survived the fetch, so the trim is a plain delete rather than a `not in ()`,
    # which is not a filter Postgres accepts.
    assert _calls_named(table, "in_") == []
    assert ("eq", "video_id", VIDEO_ID) in table.calls


def test_comments_too_many_for_one_request_are_sent_in_batches() -> None:
    store, table = _store()
    store.replace(VIDEO_ID, _comments(WRITE_BATCH_ROWS + 1))

    batches = _calls_named(table, "upsert")
    assert [len(call[1]) for call in batches] == [WRITE_BATCH_ROWS, 1]


def test_comments_are_read_back_best_liked_first() -> None:
    store, table = _store([_row(comment) for comment in _comments(3)])
    loaded = store.load(VIDEO_ID)

    assert loaded == _comments(3)
    assert ("order", "like_count", True) in table.calls
    assert ("eq", "video_id", VIDEO_ID) in table.calls


def test_a_video_with_no_comments_reads_back_as_no_comments() -> None:
    store, _ = _store([])

    assert store.load(VIDEO_ID) == []


def test_deleting_comments_names_only_the_video_they_belong_to() -> None:
    store, table = _store()
    store.delete(VIDEO_ID)

    assert ("delete",) in table.calls
    assert ("eq", "video_id", VIDEO_ID) in table.calls
