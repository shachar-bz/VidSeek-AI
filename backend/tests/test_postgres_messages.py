"""Tests for the `messages` table: one turn of a conversation."""

import pytest

from backend.storage.postgres import PostgresMessages, StoredMessage
from backend.storage.postgres.messages import TABLE_NAME
from backend.tests.fake_postgres import FakePool

CONVERSATION_ID = "33333333-3333-3333-3333-333333333333"
MESSAGE_ID = "44444444-4444-4444-4444-444444444444"

ROW = {
    "id": MESSAGE_ID,
    "conversation_id": CONVERSATION_ID,
    "role": "user",
    "content": "What does chapter 3 cover?",
    "tool_trace": None,
    "created_at": "2026-09-14T10:00:00+00:00",
}


def _messages(rows: list[dict] | None = None) -> tuple[PostgresMessages, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresMessages(pool=pool), pool


def test_a_message_is_appended_and_read_back() -> None:
    messages, pool = _messages([ROW])
    stored = messages.add(CONVERSATION_ID, "user", "What does chapter 3 cover?")

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert stored == StoredMessage(
        id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        role="user",
        content="What does chapter 3 cover?",
        tool_trace=None,
        created_at=ROW["created_at"],
    )


def test_an_assistant_message_carries_its_tool_trace() -> None:
    trace = [{"tool": "memories_semantic_search", "args": {"query": "chapter 3"}}]
    messages, pool = _messages([{**ROW, "role": "assistant", "tool_trace": trace}])
    stored = messages.add(CONVERSATION_ID, "assistant", "It covers X.", tool_trace=trace)

    assert stored.tool_trace == trace


def test_an_insert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    messages, _ = _messages([])

    with pytest.raises(RuntimeError, match="returned no row"):
        messages.add(CONVERSATION_ID, "user", "hello")


def test_a_message_that_does_not_exist_is_absence_rather_than_an_error() -> None:
    messages, _ = _messages([])

    assert messages.get(MESSAGE_ID) is None


def test_an_assistant_placeholder_is_finalized_with_content_and_trace() -> None:
    trace = [{"call_id": "call-1", "tool": "get_video_outline"}]
    row = {**ROW, "role": "assistant", "content": "Finished", "tool_trace": trace}
    messages, pool = _messages([row])

    stored = messages.update_assistant(MESSAGE_ID, "Finished", trace)

    assert stored is not None
    assert stored.content == "Finished"
    assert stored.tool_trace == trace
    assert "role = 'assistant'" in pool.statements[0]


def test_finalizing_a_missing_assistant_is_absence() -> None:
    messages, _ = _messages([])

    assert messages.update_assistant(MESSAGE_ID, "partial") is None


def test_a_conversations_messages_come_back_in_the_order_they_were_said() -> None:
    messages, pool = _messages([ROW, ROW])
    found = messages.list_for_conversation(CONVERSATION_ID)

    assert len(found) == 2
    assert "order by created_at" in pool.statements[0]
