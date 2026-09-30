"""Tests conversation CRUD, user scoping, and the SSE generation lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.dependencies import current_user
from backend.api.routes import conversations as routes
from backend.core.errors import VideoNotLinkedError
from backend.services.visual_indexing import CURRENT_VISUAL_INDEX_VERSION
from backend.services.visual_search import VISUAL_PROCESSING, VISUAL_READY, VISUAL_UNAVAILABLE
from backend.storage.postgres import StoredConversation, StoredMessage, StoredUser, VisualIndexState
from backend.video_agent import TextFragment, ToolFinished, ToolStarted
from backend.video_agent.generation import GenerationRegistry

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
VIDEO_ID = "33333333-3333-3333-3333-333333333333"
NOW = "2026-09-19T10:00:00+00:00"

USER = StoredUser(USER_ID, "person@example.com", "hash", "Person", NOW, NOW)


class MemoryConversations:
    def __init__(self) -> None:
        self.items: dict[str, StoredConversation] = {}
        self.next_id = 1

    def create(self, user_id: str, video_id: str, title=None) -> StoredConversation:
        item = StoredConversation(
            id=f"00000000-0000-0000-0000-{self.next_id:012d}",
            user_id=user_id,
            video_id=video_id,
            title=title,
            created_at=NOW,
            updated_at=NOW,
        )
        self.next_id += 1
        self.items[item.id] = item
        return item

    def get(self, conversation_id: str):
        return self.items.get(conversation_id)

    def list_for_video(self, user_id: str, video_id: str):
        return [
            item
            for item in self.items.values()
            if item.user_id == user_id and item.video_id == video_id
        ]

    def rename(self, conversation_id: str, title: str):
        item = self.items.get(conversation_id)
        if item is None:
            return None
        renamed = replace(item, title=title)
        self.items[conversation_id] = renamed
        return renamed

    def touch(self, conversation_id: str) -> None:
        return None

    def delete(self, conversation_id: str) -> None:
        self.items.pop(conversation_id, None)


class MemoryMessages:
    def __init__(self) -> None:
        self.items: dict[str, StoredMessage] = {}
        self.next_id = 1
        self._pool = object()

    def add(self, conversation_id, role, content, tool_trace=None):
        item = StoredMessage(
            id=f"10000000-0000-0000-0000-{self.next_id:012d}",
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_trace=tool_trace,
            created_at=NOW,
        )
        self.next_id += 1
        self.items[item.id] = item
        return item

    def get(self, message_id: str):
        return self.items.get(message_id)

    def update_assistant(self, message_id, content, tool_trace=None):
        item = self.items.get(message_id)
        if item is None or item.role != "assistant":
            return None
        updated = replace(item, content=content, tool_trace=tool_trace)
        self.items[message_id] = updated
        return updated

    def list_for_conversation(self, conversation_id):
        return [item for item in self.items.values() if item.conversation_id == conversation_id]


class MemoryUserVideos:
    def __init__(self, linked: bool = True) -> None:
        self.linked = linked

    def get(self, user_id, video_id):
        return object() if self.linked and user_id == USER_ID and video_id == VIDEO_ID else None


class MemoryLibraryViews:
    def __init__(
        self, *, ready: bool = True, linked: bool = True, timing_fidelity: str | None = "word"
    ) -> None:
        self.ready = ready
        self.linked = linked
        self.timing_fidelity = timing_fidelity

    def get_video(self, user_id, video_id):
        if not self.linked or user_id != USER_ID or video_id != VIDEO_ID:
            return None
        return SimpleNamespace(
            has_video_row=True,
            has_transcript=True,
            has_timed_transcript=self.timing_fidelity is not None,
            has_chapters=self.ready,
            has_embeddings=self.ready,
            has_insights=self.ready,
            job_status="complete",
            job_phase="complete",
            error_code=None,
        )


class MemoryPins:
    def list_for_video(self, user_id, video_id):
        return []


class MemoryVideoRecords:
    def __init__(self, timing_fidelity: str | None) -> None:
        self.timing_fidelity = timing_fidelity

    def get_by_id(self, video_id):
        if video_id != VIDEO_ID:
            return None
        video = type("Video", (), {"transcript_timing_fidelity": self.timing_fidelity})()
        return type("StoredVideo", (), {"video": video})()


class MemoryComments:
    def __init__(self, count: int = 0) -> None:
        self.comment_count = count

    def count(self, video_id):
        return self.comment_count if video_id == VIDEO_ID else 0


class MemoryVisualIndex:
    def __init__(self, state: VisualIndexState | None) -> None:
        self.visual_state = state

    def state(self, video_id):
        return self.visual_state if video_id == VIDEO_ID else None


class FakeRunner:
    def __init__(self, events) -> None:
        self.events = events
        self.runs = []

    async def stream(self, prompt, *, history, deps):
        self.runs.append((prompt, list(history), deps))
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event


def _app(
    *, ready=True, linked=True, runner=None, timing_fidelity="word", comment_count=0, visual_state=None
):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user] = lambda: USER
    app.state.conversations_store = MemoryConversations()
    app.state.messages_store = MemoryMessages()
    app.state.pinned_answers_store = MemoryPins()
    app.state.user_videos_store = MemoryUserVideos(linked)
    app.state.library_views_store = MemoryLibraryViews(
        ready=ready, linked=linked, timing_fidelity=timing_fidelity
    )
    app.state.video_records_store = MemoryVideoRecords(timing_fidelity)
    app.state.comments_store = MemoryComments(comment_count)
    app.state.visual_index_store = MemoryVisualIndex(visual_state)
    app.state.conversation_agent_runner = runner or FakeRunner([TextFragment("answer")])
    app.state.generation_registry = GenerationRegistry()
    return app


def _create(client: TestClient):
    response = client.post(f"/v1/videos/{VIDEO_ID}/conversations", json={})
    assert response.status_code == 201
    return response.json()["conversation_id"]


def _events(response):
    return [
        __import__("json").loads(block.split("data: ", 1)[1])
        for block in response.text.strip().split("\n\n")
    ]


def test_create_list_get_rename_and_delete() -> None:
    app = _app()
    with TestClient(app) as client:
        conversation_id = _create(client)
        listed = client.get(f"/v1/videos/{VIDEO_ID}/conversations")
        fetched = client.get(f"/v1/conversations/{conversation_id}")
        renamed = client.patch(
            f"/v1/conversations/{conversation_id}", json={"title": "Alignment details"}
        )
        deleted = client.delete(f"/v1/conversations/{conversation_id}")
        missing = client.get(f"/v1/conversations/{conversation_id}")

    assert listed.json()["conversations"][0]["conversation_id"] == conversation_id
    assert fetched.json()["messages"] == []
    assert renamed.json()["title"] == "Alignment details"
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_another_users_conversation_is_always_not_found() -> None:
    app = _app()
    foreign = app.state.conversations_store.create(OTHER_USER_ID, VIDEO_ID)
    with TestClient(app) as client:
        assert client.get(f"/v1/conversations/{foreign.id}").status_code == 404
        assert (
            client.patch(f"/v1/conversations/{foreign.id}", json={"title": "Mine"}).status_code
            == 404
        )
        assert client.delete(f"/v1/conversations/{foreign.id}").status_code == 404


def test_normal_stream_orders_fragments_tools_and_persisted_completion() -> None:
    runner = FakeRunner(
        [
            ToolStarted("call-1", "memories_semantic_search", {"query": "mono"}, NOW),
            ToolFinished("call-1", "2 results", NOW),
            TextFragment("The speaker "),
            TextFragment("requires mono audio."),
        ]
    )
    app = _app(runner=runner)
    with TestClient(app) as client:
        conversation_id = _create(client)
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"content": "What format?"}
        )
        reopened = client.get(f"/v1/conversations/{conversation_id}")

    events = _events(response)
    assert [event["type"] for event in events] == [
        "message_start",
        "tool_call",
        "tool_result",
        "token",
        "token",
        "message_complete",
    ]
    assert events[0]["user_message_id"] and events[0]["message_id"]
    assert [event["text"] for event in events if event["type"] == "token"] == [
        "The speaker ",
        "requires mono audio.",
    ]
    final = events[-1]["message"]
    assert final["content"] == "The speaker requires mono audio."
    assert final["tool_trace"][0]["call_id"] == "call-1"
    assert final["tool_trace"][0]["summary"] == "2 results"
    assert reopened.json()["messages"][-1] == final
    assert app.state.conversations_store.get(conversation_id).title == "What format?"
    assert runner.runs[0][1] == []
    assert runner.runs[0][2].video_id == VIDEO_ID


def test_a_streamed_tool_call_carries_its_activity_and_the_saved_trace_does_not() -> None:
    runner = FakeRunner(
        [
            ToolStarted("call-1", "memories_semantic_search", {"query": "mono"}, NOW),
            ToolFinished("call-1", "2 results", NOW),
            ToolStarted("call-2", "a_tool_without_a_label", {}, NOW),
            ToolFinished("call-2", None, NOW),
            TextFragment("Mono."),
        ]
    )
    app = _app(runner=runner)
    with TestClient(app) as client:
        conversation_id = _create(client)
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"content": "What format?"}
        )
        reopened = client.get(f"/v1/conversations/{conversation_id}")

    events = _events(response)
    calls = [event["call"] for event in events if event["type"] in ("tool_call", "tool_result")]
    assert [call["activity"] for call in calls] == [
        "Searching the video",
        "Searching the video",
        None,
        None,
    ]
    stored = app.state.messages_store.get(events[0]["message_id"]).tool_trace
    assert all("activity" not in call for call in stored)
    assert all(call["activity"] is None for call in events[-1]["message"]["tool_trace"])
    assert all(
        call["activity"] is None for call in reopened.json()["messages"][-1]["tool_trace"]
    )


def test_exception_after_tokens_emits_error_and_persists_the_partial_answer() -> None:
    app = _app(runner=FakeRunner([TextFragment("Partial"), RuntimeError("provider secret")]))
    with TestClient(app) as client:
        conversation_id = _create(client)
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"content": "Explain"}
        )
        reopened = client.get(f"/v1/conversations/{conversation_id}")

    events = _events(response)
    assert [event["type"] for event in events] == ["message_start", "token", "error"]
    assert "provider secret" not in response.text
    assert reopened.json()["messages"][-1]["content"] == "Partial"


def test_unlinked_video_is_not_found_and_incomplete_video_rejects_chat() -> None:
    with TestClient(_app(linked=False)) as client:
        assert client.post(f"/v1/videos/{VIDEO_ID}/conversations", json={}).status_code == 404
    with TestClient(_app(ready=False)) as client:
        response = client.post(f"/v1/videos/{VIDEO_ID}/conversations", json={})
        assert response.status_code == 409
        assert response.json()["detail"] == "Video is not ready for chat"


def test_a_link_removed_during_creation_maps_the_store_error_to_not_found() -> None:
    app = _app()

    class RemovedLinkConversations(MemoryConversations):
        def create(self, user_id: str, video_id: str, title=None):
            raise VideoNotLinkedError(video_id)

    app.state.conversations_store = RemovedLinkConversations()
    with TestClient(app) as client:
        response = client.post(f"/v1/videos/{VIDEO_ID}/conversations", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "Video is not in this user's library"


def test_both_ready_and_partial_completed_videos_are_chat_capable() -> None:
    for timing_fidelity, expected_reliable in (("word", True), (None, False)):
        runner = FakeRunner([TextFragment("answer")])
        app = _app(ready=True, runner=runner, timing_fidelity=timing_fidelity)
        with TestClient(app) as client:
            conversation_id = _create(client)
            response = client.post(
                f"/v1/conversations/{conversation_id}/messages",
                json={"content": "Where is it discussed?"},
            )

        assert response.status_code == 200
        assert runner.runs[0][2].timestamps_reliable is expected_reliable


def test_the_agent_is_told_whether_the_video_has_comments() -> None:
    """Only a video with stored comments is offered the comments tool, decided once per run."""
    for comment_count, expected in ((0, False), (37, True)):
        runner = FakeRunner([TextFragment("answer")])
        app = _app(runner=runner, comment_count=comment_count)
        with TestClient(app) as client:
            conversation_id = _create(client)
            client.post(
                f"/v1/conversations/{conversation_id}/messages",
                json={"content": "What do people think?"},
            )

        assert runner.runs[0][2].has_comments is expected


def test_the_agent_is_told_whether_the_video_s_picture_can_be_looked_at() -> None:
    """Only a ready index with the current models is looked at; queued or indexing is on its way."""
    cases = (
        (VisualIndexState("ready", None, CURRENT_VISUAL_INDEX_VERSION), VISUAL_READY),
        (VisualIndexState("ready", None, "clip@1fps"), VISUAL_UNAVAILABLE),
        (VisualIndexState("pending", None, None), VISUAL_PROCESSING),
        (VisualIndexState("indexing", None, None), VISUAL_PROCESSING),
        (VisualIndexState("failed", "ffmpeg_failed", None), VISUAL_UNAVAILABLE),
        (VisualIndexState("skipped", "ingested_before_visual_indexing", None), VISUAL_UNAVAILABLE),
        (None, VISUAL_UNAVAILABLE),
    )
    for visual_state, expected in cases:
        runner = FakeRunner([TextFragment("answer")])
        app = _app(runner=runner, visual_state=visual_state)
        with TestClient(app) as client:
            conversation_id = _create(client)
            client.post(
                f"/v1/conversations/{conversation_id}/messages",
                json={"content": "What is on the slide?"},
            )

        assert runner.runs[0][2].visual_availability == expected, visual_state


def test_the_players_position_reaches_the_agent_with_the_question() -> None:
    # "What is this?" means whatever was on screen when it was asked, so the position the
    # website sends has to arrive in the agent's deps untouched.
    runner = FakeRunner([TextFragment("answer")])
    app = _app(runner=runner)
    with TestClient(app) as client:
        conversation_id = _create(client)
        client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"content": "What is this diagram?", "current_time_seconds": 312.4, "player_paused": True},
        )
        client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"content": "And then?"}
        )

    assert (runner.runs[0][2].current_time_seconds, runner.runs[0][2].player_paused) == (312.4, True)
    assert (runner.runs[1][2].current_time_seconds, runner.runs[1][2].player_paused) == (None, None)


def test_a_negative_player_position_is_rejected() -> None:
    with TestClient(_app()) as client:
        conversation_id = _create(client)
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"content": "What is this?", "current_time_seconds": -1},
        )

    assert response.status_code == 422


def test_stop_persists_partial_text_and_emits_stopped() -> None:
    async def scenario() -> None:
        conversations = MemoryConversations()
        messages = MemoryMessages()
        conversation = conversations.create(USER_ID, VIDEO_ID)
        user_message = messages.add(conversation.id, "user", "Explain")
        assistant = messages.add(conversation.id, "assistant", "")
        registry = GenerationRegistry()
        generation = await registry.start(conversation.id)
        assert generation is not None

        class SlowRunner:
            async def stream(self, prompt, *, history, deps):
                yield TextFragment("kept")
                await asyncio.Event().wait()

        stream = routes._answer_stream(
            conversation=conversation,
            prompt="Explain",
            first_exchange=True,
            history=[],
            user_message=user_message,
            assistant=assistant,
            runner=SlowRunner(),
            generation=generation,
            generations=registry,
            conversations=conversations,
            messages=messages,
            pins=MemoryPins(),
            timestamps_reliable=True,
        )
        assert "message_start" in await anext(stream)
        assert '"text":"kept"' in await anext(stream)
        assert await registry.request_stop(conversation.id)
        stopped = await anext(stream)
        assert '"type":"stopped"' in stopped
        assert '"content":"kept"' in stopped
        assert messages.get(assistant.id).content == "kept"
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass

    asyncio.run(scenario())


def test_a_video_without_a_record_is_not_reported_as_untimed() -> None:
    assert routes._timestamps_reliable("unknown-video", MemoryVideoRecords("word")) is True
