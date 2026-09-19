"""Pins the wire values the website's contract is built on.

`frontend/src/api/types.ts` mirrors these models by hand, the same way
`chrome-extension/src/types.ts` mirrors the extension's. Nothing checks the two at build
time, so this file checks the half that a rename would silently break: the literal strings
that cross the wire. A field renamed in Python and not in TypeScript is caught by the first
request that carries it; an *enum value* renamed in Python is caught by nobody, because both
sides go on compiling and the browser simply stops recognising a stage it is shown.
"""

from backend.schemas.account import Surface
from backend.schemas.conversations import (
    ConversationMessage,
    MessageRole,
    MessageStartEvent,
    StreamEventType,
    TokenEvent,
    ToolCallTrace,
)
from backend.schemas.library import LibrarySort, LibraryVideo, SortDirection
from backend.schemas.readiness import ReadinessStage
from backend.schemas.videos import VideoDetail


def test_every_readiness_stage_keeps_the_name_the_website_switches_on() -> None:
    assert {stage.value for stage in ReadinessStage} == {
        "downloading",
        "transcribing",
        "understanding",
        "ready",
        "partial",
        "failed",
    }


def test_every_stream_event_type_keeps_its_name() -> None:
    assert {event.value for event in StreamEventType} == {
        "message_start",
        "token",
        "tool_call",
        "tool_result",
        "message_complete",
        "stopped",
        "error",
    }


def test_the_remaining_enums_keep_theirs() -> None:
    assert {role.value for role in MessageRole} == {"user", "assistant"}
    assert {surface.value for surface in Surface} == {"website", "extension"}
    assert {sort.value for sort in LibrarySort} == {"added_at", "duration"}
    assert {direction.value for direction in SortDirection} == {"asc", "desc"}


def test_a_stream_event_serializes_its_type_as_a_plain_string() -> None:
    # The browser reads `event.type` out of parsed JSON and compares it to a literal, so an
    # enum that serialized as anything but its value would never match.
    payload = TokenEvent(text="hello").model_dump(mode="json")

    assert payload == {"type": "token", "text": "hello"}


def test_message_start_carries_both_ids_before_any_token_arrives() -> None:
    # A client that receives this and nothing else still has a conversation it can reopen,
    # and an assistant message id it can pin or stop.
    event = MessageStartEvent(user_message_id="u1", message_id="a1")

    assert event.model_dump(mode="json") == {
        "type": "message_start",
        "user_message_id": "u1",
        "message_id": "a1",
    }


def test_a_library_row_for_a_video_that_has_no_row_yet_is_representable() -> None:
    # The whole of `downloading` and `transcribing`: a job, a title and a stage, and no
    # video id to click through to.
    row = LibraryVideo(
        job_id="abc",
        title="Some talk",
        source_site="example.com",
        source_url="https://example.com/talks/1",
        stage=ReadinessStage.DOWNLOADING,
        progress=0.12,
        status_message="Queued for authenticated download",
    )

    assert row.video_id is None
    assert row.added_at is None
    assert row.tags == []


def test_a_video_before_ready_carries_no_insights() -> None:
    detail = VideoDetail(
        video_id="v1",
        title="Some talk",
        original_title="Some talk",
        source_site="example.com",
        source_url="https://example.com/talks/1",
        added_at="2026-09-14T10:00:00+00:00",
        stage=ReadinessStage.UNDERSTANDING,
    )

    assert detail.insights is None
    assert detail.stage.allows_chat is False
    assert detail.stage.allows_browsing is True


def test_a_user_message_carries_no_tool_trace() -> None:
    message = ConversationMessage(
        message_id="m1", role=MessageRole.USER, content="what did they say about X?",
        created_at="2026-09-14T10:00:00+00:00",
    )

    assert message.tool_trace is None
    assert message.pinned is False


def test_a_trace_entry_still_in_flight_has_no_finish_time() -> None:
    # What a live trace shows while a slow retrieval is running.
    call = ToolCallTrace(
        call_id="c1",
        tool="memories_semantic_search",
        arguments={"query": "X"},
        started_at="2026-09-14T10:00:00+00:00",
    )

    assert call.finished_at is None
    assert call.error is None
