"""Final application composition, hosted CORS, and loopback deployment tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core import config
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager

EXTENSION_ID = "allowed-extension"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
WEBSITE_ORIGIN = "https://app.vidseek.example"
LOCAL_WEBSITE_ORIGIN = "http://127.0.0.1:5173"


def _app(tmp_path: Path):
    return create_app(
        session_registry=SessionRegistry({EXTENSION_ID}),
        job_manager=JobManager(tmp_path),
    )


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


def test_cors_admits_the_local_frontend_by_default(tmp_path: Path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.options(
            "/v1/auth/signup",
            headers={
                "Origin": LOCAL_WEBSITE_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LOCAL_WEBSITE_ORIGIN


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


def test_hosted_deployment_has_no_default_website_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDSEEK_REQUIRE_LOOPBACK", "false")
    assert config.website_origins() == set()


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
