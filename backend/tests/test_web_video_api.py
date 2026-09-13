"""Tests for extension-origin pairing and bearer authorization."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.Web_video_download.api import create_app
from backend.Web_video_download.jobs import JobManager
from backend.Web_video_download.security import SessionRegistry


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
