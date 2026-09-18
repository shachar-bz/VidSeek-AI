"""Tests for the `conversations` table: one account's threads about one video."""

from contextlib import contextmanager

import psycopg
import pytest

from backend.core.errors import VideoNotLinkedError
from backend.storage.postgres import PostgresConversations, StoredConversation
from backend.storage.postgres.conversations import TABLE_NAME
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"
CONVERSATION_ID = "33333333-3333-3333-3333-333333333333"

ROW = {
    "id": CONVERSATION_ID,
    "user_id": USER_ID,
    "video_id": VIDEO_ID,
    "title": None,
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}


def _conversations(rows: list[dict] | None = None) -> tuple[PostgresConversations, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresConversations(pool=pool), pool


def test_a_conversation_is_started_and_read_back() -> None:
    conversations, pool = _conversations([ROW])
    stored = conversations.create(USER_ID, VIDEO_ID)

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert stored == StoredConversation(
        id=CONVERSATION_ID,
        user_id=USER_ID,
        video_id=VIDEO_ID,
        title=None,
        created_at=ROW["created_at"],
        updated_at=ROW["updated_at"],
    )


def test_starting_a_conversation_about_an_unlinked_video_is_a_named_error() -> None:
    @contextmanager
    def raising_connection():
        raise psycopg.errors.ForeignKeyViolation("violates foreign key constraint")
        yield  # pragma: no cover - unreachable, but keeps this a generator function

    pool = FakePool(rows=[])
    pool.connection = raising_connection
    conversations = PostgresConversations(pool=pool)

    with pytest.raises(VideoNotLinkedError, match=VIDEO_ID):
        conversations.create(USER_ID, VIDEO_ID)


def test_a_conversation_missing_from_the_database_is_absence_rather_than_an_error() -> None:
    conversations, _ = _conversations([])

    assert conversations.get(CONVERSATION_ID) is None


def test_a_videos_conversations_come_back_most_recently_used_first() -> None:
    conversations, pool = _conversations([ROW, ROW])
    found = conversations.list_for_video(USER_ID, VIDEO_ID)

    assert len(found) == 2
    assert "order by updated_at desc" in pool.statements[0]


def test_renaming_sets_the_title() -> None:
    conversations, pool = _conversations([{**ROW, "title": "Talk about chapter 3"}])
    stored = conversations.rename(CONVERSATION_ID, "Talk about chapter 3")

    assert stored is not None and stored.title == "Talk about chapter 3"
    assert pool.recorded[0].parameters == ("Talk about chapter 3", CONVERSATION_ID)


def test_renaming_a_conversation_that_does_not_exist_is_absence_rather_than_an_error() -> None:
    conversations, _ = _conversations([])

    assert conversations.rename(CONVERSATION_ID, "New title") is None


def test_touching_bumps_updated_at() -> None:
    conversations, pool = _conversations([])
    conversations.touch(CONVERSATION_ID)

    assert "update public.conversations set updated_at = now()" in pool.statements[0]
    assert pool.recorded[0].parameters == (CONVERSATION_ID,)


def test_deleting_a_conversation_takes_its_messages_and_pins_with_it_via_the_foreign_keys() -> None:
    conversations, pool = _conversations([])
    conversations.delete(CONVERSATION_ID)

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (CONVERSATION_ID,)
