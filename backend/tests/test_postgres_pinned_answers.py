"""Tests for the `pinned_answers` table: assistant messages an account chose to keep."""

import pytest

from backend.storage.postgres import PinnedAnswerForVideo, PostgresPinnedAnswers, StoredPinnedAnswer
from backend.storage.postgres.pinned_answers import TABLE_NAME
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"
CONVERSATION_ID = "33333333-3333-3333-3333-333333333333"
MESSAGE_ID = "44444444-4444-4444-4444-444444444444"
PIN_ID = "55555555-5555-5555-5555-555555555555"

PIN_ROW = {
    "id": PIN_ID,
    "message_id": MESSAGE_ID,
    "created_at": "2026-09-14T10:00:00+00:00",
}

VIDEO_ROW = {
    "id": PIN_ID,
    "message_id": MESSAGE_ID,
    "conversation_id": CONVERSATION_ID,
    "content": "It covers X.",
    "message_created_at": "2026-09-14T09:55:00+00:00",
    "pinned_at": "2026-09-14T10:00:00+00:00",
}


def _pins(rows: list[dict] | None = None) -> tuple[PostgresPinnedAnswers, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresPinnedAnswers(pool=pool), pool


def test_pinning_a_message_inserts_and_reads_the_pin_back() -> None:
    pins, pool = _pins([PIN_ROW])
    stored = pins.pin(MESSAGE_ID)

    assert f"insert into public.{TABLE_NAME}" in pool.statements[0]
    assert "on conflict (message_id) do nothing" in pool.statements[0]
    assert stored == StoredPinnedAnswer(
        id=PIN_ID, message_id=MESSAGE_ID, created_at=PIN_ROW["created_at"]
    )


def test_pinning_an_already_pinned_message_hands_back_the_existing_pin() -> None:
    pins, _ = _pins([PIN_ROW])

    assert pins.pin(MESSAGE_ID).id == PIN_ID


def test_a_pin_that_was_not_accepted_is_an_error_rather_than_a_silent_success() -> None:
    pins, _ = _pins([])

    with pytest.raises(RuntimeError, match="returned no row"):
        pins.pin(MESSAGE_ID)


def test_unpinning_leaves_the_message_alone() -> None:
    pins, pool = _pins([])
    pins.unpin(MESSAGE_ID)

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (MESSAGE_ID,)


def test_a_videos_pins_come_back_with_their_way_back_to_the_conversation() -> None:
    pins, pool = _pins([VIDEO_ROW])
    found = pins.list_for_video(USER_ID, VIDEO_ID)

    assert found == [
        PinnedAnswerForVideo(
            id=PIN_ID,
            message_id=MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            content="It covers X.",
            message_created_at=VIDEO_ROW["message_created_at"],
            pinned_at=VIDEO_ROW["pinned_at"],
        )
    ]
    assert pool.recorded[0].parameters == (USER_ID, VIDEO_ID)


def test_pins_for_a_video_come_back_most_recently_pinned_first() -> None:
    pins, pool = _pins([VIDEO_ROW, VIDEO_ROW])
    found = pins.list_for_video(USER_ID, VIDEO_ID)

    assert len(found) == 2
    assert "order by p.created_at desc" in pool.statements[0]
