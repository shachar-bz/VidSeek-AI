"""Tests for the `comments` table a YouTube video's top comments are written to."""

from datetime import datetime, timezone

from backend.services.video_download.youtube.comments import CommentEntry
from backend.storage.postgres import PostgresComments
from backend.storage.postgres.comments import TABLE_NAME
from backend.tests.fake_postgres import FakePool

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

COMMENTS = [
    CommentEntry(
        id="comment-1",
        author="A Viewer",
        text="great video",
        like_count=12,
        reply_count=1,
        published_at="2026-09-14T10:00:00+00:00",
    ),
    CommentEntry(
        id="comment-2",
        author="Another Viewer",
        text="thanks",
        like_count=3,
        reply_count=0,
        published_at="2026-09-14T11:00:00+00:00",
    ),
]


def _rows(comments: list[CommentEntry]) -> list[dict]:
    return [
        {
            "id": comment.id,
            "video_id": VIDEO_ID,
            "author": comment.author,
            "text": comment.text,
            "like_count": comment.like_count,
            "reply_count": comment.reply_count,
            "published_at": comment.published_at,
        }
        for comment in comments
    ]


def _comments(rows: list[dict] | None = None) -> tuple[PostgresComments, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresComments(pool=pool), pool


def test_comments_are_written_as_one_statement_per_batch_not_per_comment() -> None:
    comments, pool = _comments()
    written = comments.replace(VIDEO_ID, COMMENTS)

    assert written == len(COMMENTS)
    assert pool.recorded[0].many is True
    assert len(pool.recorded[0].parameters) == len(COMMENTS)


def test_a_comment_carries_its_like_and_reply_counts() -> None:
    # The like count is not decoration: it is the order this table is read back in.
    comments, pool = _comments()
    comments.replace(VIDEO_ID, COMMENTS)

    assert pool.recorded[0].parameters[0] == (
        "comment-1",
        VIDEO_ID,
        "A Viewer",
        "great video",
        12,
        1,
        "2026-09-14T10:00:00+00:00",
    )


def test_a_refetched_comment_is_overwritten_in_place() -> None:
    # The id is YouTube's own thread id, so a second fetch of the same video updates each
    # comment rather than adding a second copy of it with a newer like count.
    comments, pool = _comments()
    comments.replace(VIDEO_ID, COMMENTS)

    assert "on conflict (id) do update set" in pool.statements[0]
    assert "like_count = excluded.like_count" in pool.statements[0]


def test_comments_the_new_fetch_did_not_bring_back_are_dropped() -> None:
    comments, pool = _comments()
    comments.replace(VIDEO_ID, COMMENTS)

    assert "id != all(%s)" in pool.statements[-1]
    assert pool.recorded[-1].parameters == (VIDEO_ID, ["comment-1", "comment-2"])


def test_a_fetch_that_found_nothing_clears_the_video_s_comments() -> None:
    # An empty fetch still means something -- comments were turned off, or all removed --
    # and the array parameter makes that the same statement rather than a special case.
    comments, pool = _comments()
    written = comments.replace(VIDEO_ID, [])

    assert written == 0
    assert not any(item.many for item in pool.recorded)
    assert pool.recorded[-1].parameters == (VIDEO_ID, [])


def test_the_write_and_the_trim_are_one_transaction() -> None:
    comments, pool = _comments()
    comments.replace(VIDEO_ID, COMMENTS)

    assert pool.transactions == 1


def test_comments_come_back_best_liked_first() -> None:
    comments, pool = _comments(_rows(COMMENTS))
    loaded = comments.load(VIDEO_ID)

    assert [comment.id for comment in loaded] == ["comment-1", "comment-2"]
    assert "order by like_count desc" in pool.statements[0]


def test_a_published_time_comes_back_as_text_whatever_the_driver_decoded_it_into() -> None:
    # `published_at` is a timestamptz and the driver hands back a datetime; CommentEntry
    # carries the ISO string the YouTube API gave.
    moment = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    rows = _rows(COMMENTS[:1])
    rows[0]["published_at"] = moment
    comments, _ = _comments(rows)

    assert comments.load(VIDEO_ID)[0].published_at == "2026-09-14T10:00:00+00:00"


def test_a_video_with_no_comments_is_an_empty_list_rather_than_an_error() -> None:
    comments, _ = _comments([])

    assert comments.load(VIDEO_ID) == []


def test_deleting_comments_is_scoped_to_one_video() -> None:
    comments, pool = _comments()
    comments.delete(VIDEO_ID)

    assert pool.statements[0] == f"delete from public.{TABLE_NAME} where video_id = %s::uuid"
    assert pool.recorded[0].parameters == (VIDEO_ID,)
