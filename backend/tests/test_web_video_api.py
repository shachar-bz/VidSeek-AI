"""Tests for extension-origin pairing and bearer authorization."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core.auth import UserAuthRegistry, hash_password
from backend.core.security import SessionRegistry
from backend.schemas.video_jobs import JobPhase, JobStatus, VideoJobResponse
from backend.services.video_download.jobs import JobManager
from backend.storage.postgres import PostgresSessions, PostgresUsers
from backend.tests.fake_postgres import FakePool

USER_ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "email": "person@example.com",
    "password_hash": hash_password("irrelevant"),
    "display_name": None,
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}

SESSION_ROW = {
    "id": "22222222-3333-4444-5555-666666666666",
    "user_id": USER_ROW["id"],
    "surface": "extension",
    "created_at": "2026-09-14T10:00:00+00:00",
    "last_used_at": "2026-09-14T10:00:00+00:00",
    "expires_at": "2026-09-21T10:00:00+00:00",
}


class RecordingJobManager(JobManager):
    """A `JobManager` that remembers what it was asked to create instead of running it."""

    def __init__(self, download_root: Path):
        super().__init__(download_root)
        self.calls: list[tuple[object, str | None]] = []

    def create(self, request, user_id: str | None = None) -> VideoJobResponse:
        self.calls.append((request, user_id))
        return VideoJobResponse(
            job_id="job-1",
            status=JobStatus.QUEUED,
            phase=JobPhase.DOWNLOAD,
            progress=0.0,
            message="Queued",
            acquisition_mode="companion_download",
            can_capture=False,
        )


def test_session_rejects_web_page_origin(tmp_path: Path) -> None:
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(tmp_path),
    )
    with TestClient(app) as client:
        response = client.post("/v1/session", headers={"Origin": "https://malicious.example"})
    assert response.status_code == 403


def test_job_endpoint_requires_token_bound_to_origin(tmp_path: Path) -> None:
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(tmp_path),
    )
    origin = "chrome-extension://allowed"
    with TestClient(app) as client:
        session = client.post("/v1/session", headers={"Origin": origin})
        token = session.json()["token"]
        response = client.get(
            "/v1/video-jobs/missing",
            headers={"Origin": origin, "Authorization": f"Bearer {token}"},
        )
        wrong_origin = client.get(
            "/v1/video-jobs/missing",
            headers={"Origin": "chrome-extension://different", "Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404
    assert wrong_origin.status_code == 401


def test_status_polling_works_without_an_origin_header(tmp_path: Path) -> None:
    """Chrome may omit Origin on a service-worker GET; polling must not 401 for it."""
    registry = SessionRegistry({"allowed"})
    app = create_app(session_registry=registry, job_manager=JobManager(tmp_path))
    token = registry.create("chrome-extension://allowed")
    with TestClient(app) as client:
        response = client.get(
            "/v1/video-jobs/unknown", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404


def test_an_origin_that_is_sent_must_still_match(tmp_path: Path) -> None:
    registry = SessionRegistry({"allowed"})
    app = create_app(session_registry=registry, job_manager=JobManager(tmp_path))
    token = registry.create("chrome-extension://allowed")
    with TestClient(app) as client:
        response = client.get(
            "/v1/video-jobs/unknown",
            headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
        )
    assert response.status_code == 401


def test_starting_work_still_requires_the_origin_header(tmp_path: Path) -> None:
    registry = SessionRegistry({"allowed"})
    app = create_app(session_registry=registry, job_manager=JobManager(tmp_path))
    token = registry.create("chrome-extension://allowed")
    with TestClient(app) as client:
        response = client.post(
            "/v1/video-jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"page_url": "https://example.com/watch"},
        )
    assert response.status_code == 401


def test_starting_work_requires_a_signed_in_account(tmp_path: Path) -> None:
    # The extension session in Authorization proves this is the allowed extension; it says
    # nothing about which account is using it, which is what the video row needs to record.
    registry = SessionRegistry({"allowed"})
    app = create_app(session_registry=registry, job_manager=JobManager(tmp_path))
    token = registry.create("chrome-extension://allowed")
    with TestClient(app) as client:
        response = client.post(
            "/v1/video-jobs",
            headers={"Authorization": f"Bearer {token}", "Origin": "chrome-extension://allowed"},
            json={"page_url": "https://example.com/watch"},
        )
    assert response.status_code == 401


def test_starting_work_records_which_account_asked_for_it(tmp_path: Path) -> None:
    registry = SessionRegistry({"allowed"})
    auth_registry = UserAuthRegistry(PostgresSessions(pool=FakePool(rows=[SESSION_ROW])))
    user_token = auth_registry.issue(USER_ROW["id"], "extension")
    manager = RecordingJobManager(tmp_path)
    app = create_app(
        session_registry=registry,
        job_manager=manager,
        user_auth_registry=auth_registry,
        users_store=PostgresUsers(pool=FakePool(rows=[USER_ROW])),
    )
    session_token = registry.create("chrome-extension://allowed")
    with TestClient(app) as client:
        response = client.post(
            "/v1/video-jobs",
            headers={
                "Authorization": f"Bearer {session_token}",
                "Origin": "chrome-extension://allowed",
                "X-VidSeek-User-Token": user_token,
            },
            json={"page_url": "https://example.com/watch"},
        )
    assert response.status_code == 200
    assert manager.calls == [(manager.calls[0][0], USER_ROW["id"])]
