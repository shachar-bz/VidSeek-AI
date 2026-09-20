"""Final application composition, hosted CORS, and loopback deployment tests."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core import config
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager

EXTENSION_ID = "allowed-extension"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
WEBSITE_ORIGIN = "https://app.vidseek.example"


def _app(tmp_path: Path):
    return create_app(
        session_registry=SessionRegistry({EXTENSION_ID}),
        job_manager=JobManager(tmp_path),
    )


def test_every_merged_route_is_mounted_exactly_once(tmp_path: Path) -> None:
    app = _app(tmp_path)
    mounted = Counter(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    )
    expected = {
        ("GET", "/health"),
        ("POST", "/v1/session"),
        ("POST", "/v1/auth/signup"),
        ("POST", "/v1/auth/login"),
        ("GET", "/v1/auth/me"),
        ("POST", "/v1/auth/logout"),
        ("GET", "/v1/auth/sessions"),
        ("DELETE", "/v1/auth/sessions/{session_id}"),
        ("POST", "/v1/auth/sessions/revoke-all"),
        ("PATCH", "/v1/account"),
        ("POST", "/v1/account/password"),
        ("DELETE", "/v1/account"),
        ("GET", "/v1/library"),
        ("GET", "/v1/library/tags"),
        ("GET", "/v1/library/events"),
        ("PATCH", "/v1/library/{video_id}"),
        ("DELETE", "/v1/library/{video_id}"),
        ("GET", "/v1/videos/{video_id}"),
        ("GET", "/v1/videos/{video_id}/playback"),
        ("GET", "/v1/videos/{video_id}/transcript"),
        ("GET", "/v1/videos/{video_id}/outline"),
        ("GET", "/v1/videos/{video_id}/pins"),
        ("POST", "/v1/videos/{video_id}/pins"),
        ("DELETE", "/v1/videos/{video_id}/pins/{message_id}"),
        ("GET", "/v1/videos/{video_id}/conversations"),
        ("POST", "/v1/videos/{video_id}/conversations"),
        ("GET", "/v1/conversations/{conversation_id}"),
        ("PATCH", "/v1/conversations/{conversation_id}"),
        ("DELETE", "/v1/conversations/{conversation_id}"),
        ("POST", "/v1/conversations/{conversation_id}/messages"),
        ("POST", "/v1/conversations/{conversation_id}/stop"),
        ("POST", "/v1/video-jobs"),
        ("GET", "/v1/video-jobs/{job_id}"),
        ("POST", "/v1/video-jobs/{job_id}/download-complete"),
        ("POST", "/v1/video-jobs/{job_id}/capture"),
        ("POST", "/v1/video-jobs/{job_id}/cancel"),
    }

    assert expected <= mounted.keys()
    assert all(mounted[route] == 1 for route in expected)


@pytest.mark.parametrize(
    ("origin", "method"),
    [(WEBSITE_ORIGIN, "PATCH"), (EXTENSION_ORIGIN, "DELETE")],
)
def test_cors_admits_configured_website_and_extension_origins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin: str,
    method: str,
) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", WEBSITE_ORIGIN)
    monkeypatch.setenv("VIDSEEK_EXTENSION_IDS", EXTENSION_ID)
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.options(
            "/v1/account",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    allowed_methods = response.headers["access-control-allow-methods"]
    assert all(
        required in allowed_methods for required in ("GET", "POST", "PATCH", "DELETE")
    )


def test_cors_does_not_admit_an_unconfigured_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", WEBSITE_ORIGIN)
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.options(
            "/v1/account",
            headers={
                "Origin": "https://malicious.example",
                "Access-Control-Request-Method": "PATCH",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_loopback_is_required_by_default(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.get("/health")
    assert response.status_code == 403


def test_hosted_deployment_can_disable_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VIDSEEK_REQUIRE_LOOPBACK", "false")
    app = _app(tmp_path)
    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_startup_and_health_need_no_database_or_blob_configuration(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert app.state.blob_video_storage is None


def test_wildcard_website_origin_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit origins"):
        _app(tmp_path)


def test_loopback_setting_rejects_ambiguous_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDSEEK_REQUIRE_LOOPBACK", "sometimes")
    with pytest.raises(RuntimeError, match="must be true or false"):
        config.require_loopback()
