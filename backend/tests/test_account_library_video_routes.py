"""Route-level coverage for hosted account, library, and video APIs."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.dependencies import current_user, sessions_store, users_store
from backend.api.routes import account, library, videos
from backend.core.auth import hash_password
from backend.schemas.readiness import ReadinessStage
from backend.services.library_changes import LibraryChangeNotifier
from backend.storage.postgres import (
    LibraryViewRow,
    PinnedAnswerForVideo,
    PostgresLibraryViews,
    PostgresTranscriptSegments,
    StoredUser,
)
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-2222-3333-4444-555555555555"
VIDEO_ID = "22222222-3333-4444-5555-666666666666"
MESSAGE_ID = "33333333-4444-5555-6666-777777777777"

USER = StoredUser(
    id=USER_ID,
    email="person@example.com",
    password_hash=hash_password("current password"),
    display_name="Person",
    created_at="2026-09-19T10:00:00+00:00",
    updated_at="2026-09-19T10:00:00+00:00",
)


def _row(**changes) -> LibraryViewRow:
    base = LibraryViewRow(
        video_id=VIDEO_ID,
        job_id="job-1",
        original_title="Original",
        custom_title=None,
        source="youtube_pipeline",
        source_url="https://www.youtube.com/watch?v=abc",
        duration_seconds=90.0,
        tags=["research"],
        added_at="2026-09-19T10:00:00+00:00",
        job_status="complete",
        job_phase="complete",
        progress=1.0,
        status_message="Complete",
        error_code=None,
        conversation_count=1,
        has_video_row=True,
        has_transcript=True,
        has_chapters=True,
        has_embeddings=True,
        has_insights=True,
        transcript_source="captions",
        transcript_language="en",
        transcript_timing_fidelity="caption",
        blob_container="videos",
        blob_name="videos/id/file.mp4",
        insights_summary="Summary",
        insights_takeaways=["One"],
        insights_suggested_questions=["Why?"],
    )
    return replace(base, **changes)


def _app(*routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router.router)
    app.dependency_overrides[current_user] = lambda: USER
    return app


def test_library_listing_derives_readiness_and_uses_one_aggregate_query() -> None:
    db_row = {
        **vars(_row()),
        "page_title": None,
        "page_url": None,
        "total": 1,
    }
    pool = FakePool(rows=[db_row])
    app = _app(library)
    app.state.library_views_store = PostgresLibraryViews(pool=pool)

    response = TestClient(app).get("/v1/library")

    assert response.status_code == 200
    assert response.json()["videos"][0]["stage"] == "ready"
    assert response.json()["videos"][0]["source"] == "youtube_pipeline"
    assert response.json()["videos"][0]["thumbnail_url"] == f"/v1/videos/{VIDEO_ID}/thumbnail"
    assert len(pool.recorded) == 1
    assert "has_transcript" in pool.statements[0]


def test_library_lists_a_processing_job_without_a_video_id() -> None:
    row = _row(
        video_id=None,
        added_at=None,
        job_status="running",
        job_phase="transcription",
        has_video_row=False,
        has_transcript=False,
        has_chapters=False,
        has_embeddings=False,
        has_insights=False,
    )
    pool = FakePool(rows=[{**vars(row), "page_title": None, "page_url": None, "total": 1}])
    app = _app(library)
    app.state.library_views_store = PostgresLibraryViews(pool=pool)

    item = TestClient(app).get("/v1/library").json()["videos"][0]

    assert item["video_id"] is None
    assert item["stage"] == "transcribing"


def test_empty_library_page_still_reports_the_filtered_total() -> None:
    pool = FakePool(rows=[{"video_id": None, "job_id": None, "total": 7}])
    app = _app(library)
    app.state.library_views_store = PostgresLibraryViews(pool=pool)

    body = TestClient(app).get("/v1/library?offset=50").json()

    assert body["videos"] == []
    assert body["total"] == 7


PROCESSING_ROW = _row(
    video_id=None,
    job_status="running",
    job_phase="transcription",
    has_video_row=False,
    has_transcript=False,
    has_chapters=False,
    has_embeddings=False,
    has_insights=False,
)


class ScriptedProgressViews:
    """`progress_rows` answers in order, repeating the last answer once they run out."""

    def __init__(self, *answers: list[LibraryViewRow]):
        self.answers = list(answers)
        self.reads = 0

    def progress_rows(self, user_id):
        self.reads += 1
        return self.answers[min(self.reads, len(self.answers)) - 1]


def _progress_stream(views, changes, *, keepalive_seconds=60.0):
    return library.library_progress_stream(
        USER_ID, views, changes, keepalive_seconds=keepalive_seconds, coalesce_seconds=0
    )


def test_events_route_streams_server_sent_events() -> None:
    # Called directly: the stream never ends, and TestClient waits for a body to finish.
    response = asyncio.run(
        library.library_events(USER, ScriptedProgressViews([]), LibraryChangeNotifier())
    )

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"


def test_progress_stream_sends_a_job_the_extension_starts_while_idle() -> None:
    new_job = replace(PROCESSING_ROW, job_id="job-2")
    views = ScriptedProgressViews([_row()], [_row(), new_job])
    changes = LibraryChangeNotifier()

    async def scenario():
        stream = _progress_stream(views, changes)
        snapshot = await anext(stream)
        changes.notify(USER_ID)
        pushed = await anext(stream)
        await stream.aclose()
        return snapshot, pushed

    snapshot, pushed = asyncio.run(scenario())

    assert '"job_id":"job-1"' in snapshot and '"stage":"ready"' in snapshot
    # Only the new job: the unchanged finished row is not sent a second time.
    assert '"job_id":"job-2"' in pushed and '"stage":"transcribing"' in pushed
    assert views.reads == 2


def test_progress_stream_gains_a_video_id_and_reaches_ready_on_notify() -> None:
    views = ScriptedProgressViews([PROCESSING_ROW], [_row()])
    changes = LibraryChangeNotifier()

    async def scenario():
        stream = _progress_stream(views, changes)
        processing = await anext(stream)
        changes.notify(USER_ID)
        finished = await anext(stream)
        await stream.aclose()
        return processing, finished

    processing, finished = asyncio.run(scenario())

    assert '"video_id":null' in processing
    assert f'"video_id":"{VIDEO_ID}"' in finished
    assert '"stage":"ready"' in finished


def test_idle_progress_stream_sends_keepalives_without_reading_again() -> None:
    views = ScriptedProgressViews([_row()])

    async def scenario():
        stream = _progress_stream(views, LibraryChangeNotifier(), keepalive_seconds=0.01)
        sent = [await anext(stream) for _ in range(3)]
        await stream.aclose()
        return sent

    sent = asyncio.run(scenario())

    assert sent[1:] == [": keepalive\n\n", ": keepalive\n\n"]
    assert views.reads == 1


def test_active_progress_stream_rereads_on_keepalive_without_a_notify() -> None:
    views = ScriptedProgressViews([PROCESSING_ROW], [_row()])

    async def scenario():
        stream = _progress_stream(views, LibraryChangeNotifier(), keepalive_seconds=0.01)
        sent = [await anext(stream) for _ in range(3)]
        await stream.aclose()
        return sent

    processing, keepalive, finished = asyncio.run(scenario())

    assert '"stage":"transcribing"' in processing
    assert keepalive == ": keepalive\n\n"
    assert '"stage":"ready"' in finished


class StubViews:
    def __init__(self, row=None):
        self.row = row

    def get_video(self, user_id, video_id):
        return self.row


class StubLinks:
    def __init__(self):
        self.title_calls = []
        self.tags_calls = []
        self.unlinked = []

    def get(self, user_id, video_id):
        return object()

    def rename(self, user_id, video_id, title):
        self.title_calls.append(title)

    def set_tags(self, user_id, video_id, tags):
        self.tags_calls.append(tags)

    def unlink(self, user_id, video_id):
        self.unlinked.append((user_id, video_id))


def test_custom_title_distinguishes_absent_from_explicit_null() -> None:
    links = StubLinks()
    app = _app(library)
    app.state.user_videos_store = links
    app.state.library_views_store = StubViews(_row())
    client = TestClient(app)

    assert client.patch(f"/v1/library/{VIDEO_ID}", json={"tags": ["x"]}).status_code == 200
    assert links.title_calls == []
    assert client.patch(f"/v1/library/{VIDEO_ID}", json={"custom_title": None}).status_code == 200
    assert links.title_calls == [None]


def test_unlink_removes_only_the_private_library_link() -> None:
    links = StubLinks()
    app = _app(library)
    app.state.user_videos_store = links

    response = TestClient(app).delete(f"/v1/library/{VIDEO_ID}")

    assert response.status_code == 204
    assert links.unlinked == [(USER_ID, VIDEO_ID)]


class StubJobs:
    def __init__(self, deletable=True):
        self.deletable = deletable
        self.deleted = []

    def delete_finished_without_video(self, job_id, user_id):
        self.deleted.append((job_id, user_id))
        return self.deletable


def test_failed_job_without_a_video_can_be_dismissed() -> None:
    jobs = StubJobs()
    app = _app(library)
    app.state.video_jobs_store = jobs

    response = TestClient(app).delete("/v1/library/jobs/job-1")

    assert response.status_code == 204
    assert jobs.deleted == [("job-1", USER_ID)]


def test_running_or_foreign_job_is_not_dismissed() -> None:
    app = _app(library)
    app.state.video_jobs_store = StubJobs(deletable=False)

    assert TestClient(app).delete("/v1/library/jobs/job-1").status_code == 404


def test_foreign_video_is_hidden_as_not_found() -> None:
    app = _app(videos)
    app.state.library_views_store = StubViews(None)
    response = TestClient(app).get(f"/v1/videos/{VIDEO_ID}")
    assert response.status_code == 404


class StubBlob:
    def __init__(self, exists=True, thumbnail_exists=True):
        self.exists = exists
        self.has_thumbnail = thumbnail_exists
        self.calls = []

    def video_exists(self, name):
        return self.exists

    def sas_download_url(self, name, expires):
        self.calls.append((name, expires))
        return f"https://blob.example/{name}?sig=fresh"

    def thumbnail_exists(self, name):
        return self.has_thumbnail

    def read_thumbnail(self, name):
        return b"jpeg-bytes"


def test_playback_mints_a_fresh_url_and_missing_blob_does_not_affect_detail() -> None:
    app = _app(videos)
    app.state.library_views_store = StubViews(_row())
    blob = StubBlob()
    app.state.blob_video_storage = blob
    client = TestClient(app)

    playback = client.get(f"/v1/videos/{VIDEO_ID}/playback")
    detail = client.get(f"/v1/videos/{VIDEO_ID}")

    assert playback.status_code == 200
    assert playback.json()["expires_in_seconds"] == 3600
    assert blob.calls == [("videos/id/file.mp4", 3600)]
    assert detail.status_code == 200
    app.state.blob_video_storage = StubBlob(exists=False)
    assert client.get(f"/v1/videos/{VIDEO_ID}/playback").status_code == 404
    assert client.get(f"/v1/videos/{VIDEO_ID}").status_code == 200


def test_thumbnail_is_private_jpeg_content() -> None:
    app = _app(videos)
    app.state.library_views_store = StubViews(_row())
    app.state.blob_video_storage = StubBlob()

    response = TestClient(app).get(f"/v1/videos/{VIDEO_ID}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"jpeg-bytes"


def test_transcript_preserves_lines_and_timing_fidelity() -> None:
    pool = FakePool(
        rows=[
            {
                "segment_index": 0,
                "start_seconds": 1.25,
                "end_seconds": 2.5,
                "text": "Hello",
            }
        ]
    )
    app = _app(videos)
    app.state.library_views_store = StubViews(_row(transcript_timing_fidelity="word"))
    app.state.transcript_segments_store = PostgresTranscriptSegments(pool=pool)

    body = TestClient(app).get(f"/v1/videos/{VIDEO_ID}/transcript").json()

    assert body["timing_fidelity"] == "word"
    assert body["lines"] == [
        {"index": 0, "start_seconds": 1.25, "end_seconds": 2.5, "text": "Hello"}
    ]


def test_video_detail_reports_how_far_the_visual_index_is() -> None:
    app = _app(videos)
    client = TestClient(app)

    app.state.library_views_store = StubViews(_row(visual_status="indexing"))
    indexing = client.get(f"/v1/videos/{VIDEO_ID}").json()
    app.state.library_views_store = StubViews(_row(visual_status=None))
    unknown = client.get(f"/v1/videos/{VIDEO_ID}").json()

    # A video is ready to chat about before its index is; the two are reported apart.
    assert indexing["stage"] == ReadinessStage.READY.value
    assert indexing["visual_status"] == "indexing"
    assert unknown["visual_status"] is None


class StubPins:
    def __init__(self):
        self.pin_calls = 0

    def pin_for_video(self, user_id, video_id, message_id):
        self.pin_calls += 1
        return PinnedAnswerForVideo(
            id="pin-1",
            message_id=message_id,
            conversation_id="conversation-1",
            content="Answer",
            pinned_at="2026-09-19T10:00:00+00:00",
        )


def test_pinning_the_same_message_is_idempotent_at_the_route_contract() -> None:
    app = _app(videos)
    app.state.library_views_store = StubViews(_row())
    pins = StubPins()
    app.state.pinned_answers_store = pins
    client = TestClient(app)

    first = client.post(f"/v1/videos/{VIDEO_ID}/pins", json={"message_id": MESSAGE_ID})
    second = client.post(f"/v1/videos/{VIDEO_ID}/pins", json={"message_id": MESSAGE_ID})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_cross_user_message_cannot_be_pinned() -> None:
    app = _app(videos)
    app.state.library_views_store = StubViews(_row())

    class RejectPins:
        def pin_for_video(self, user_id, video_id, message_id):
            return None

    app.state.pinned_answers_store = RejectPins()
    response = TestClient(app).post(
        f"/v1/videos/{VIDEO_ID}/pins", json={"message_id": MESSAGE_ID}
    )
    assert response.status_code == 404


class StubUsers:
    def __init__(self):
        self.deleted = False
        self.password_hash = None

    def update_display_name(self, user_id, name):
        return replace(USER, display_name=name)

    def update_password_hash(self, user_id, password_hash):
        self.password_hash = password_hash
        return True

    def delete(self, user_id):
        self.deleted = True
        return True


class StubSessions:
    def __init__(self):
        self.revoked = []

    def revoke_all(self, user_id):
        self.revoked.append(user_id)


def test_account_profile_password_and_deletion() -> None:
    app = _app(account)
    users = StubUsers()
    sessions = StubSessions()
    app.dependency_overrides[users_store] = lambda: users
    app.dependency_overrides[sessions_store] = lambda: sessions
    client = TestClient(app)

    profile = client.patch("/v1/account", json={"display_name": "Renamed"})
    password = client.post(
        "/v1/account/password",
        json={"current_password": "current password", "new_password": "new password"},
    )
    deletion = client.request("DELETE", "/v1/account", json={"password": "current password"})

    assert profile.json()["display_name"] == "Renamed"
    assert password.status_code == 204
    assert sessions.revoked == [USER_ID]
    assert deletion.status_code == 204
    assert users.deleted is True
