"""Tests for the /health liveness probe."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager


def test_health_reports_configured_download_root(tmp_path: Path) -> None:
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(tmp_path),
    )
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["download_root"] == str(tmp_path)
