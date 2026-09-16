"""Tests for the signup, login, /v1/auth/me and logout routes."""

from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core.auth import UserAuthRegistry, hash_password
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager
from backend.storage.postgres import PostgresUsers
from backend.tests.fake_postgres import FakePool

ORIGIN = "chrome-extension://allowed"

ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "email": "person@example.com",
    "password_hash": hash_password("the real password"),
    "display_name": "Person",
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}


@pytest.fixture(autouse=True)
def configured_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route in this file checks `is_postgres_configured()` before touching the store."""
    monkeypatch.setenv(
        "AZURE_DATABASE_URL", "postgresql://u:p@host.postgres.database.azure.com:5432/db?sslmode=require"
    )


def _app(rows: list[dict] | None = None):
    pool = FakePool(rows=rows if rows is not None else [])
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(Path.cwd()),
        user_auth_registry=UserAuthRegistry(),
        users_store=PostgresUsers(pool=pool),
    )
    return app, pool


def test_signup_from_a_disallowed_origin_is_refused() -> None:
    app, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": "https://malicious.example"},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 403


def test_signup_without_a_configured_database_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DATABASE_URL", raising=False)
    app, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": ORIGIN},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 503


def test_signup_returns_a_token_and_the_new_account() -> None:
    app, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": ORIGIN},
            json={"email": "Person@Example.com", "password": "correct horse", "display_name": "Person"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["user"] == {"id": ROW["id"], "email": "person@example.com", "display_name": "Person"}


def test_signup_with_a_taken_email_is_a_conflict() -> None:
    @contextmanager
    def raise_unique_violation():
        raise psycopg.errors.UniqueViolation("duplicate key")
        yield  # pragma: no cover - unreachable, but keeps this a generator function

    pool = FakePool()
    pool.connection = raise_unique_violation
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(Path.cwd()),
        user_auth_registry=UserAuthRegistry(),
        users_store=PostgresUsers(pool=pool),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "correct horse"},
        )
    assert response.status_code == 409
    assert "person@example.com" in response.json()["detail"]


def test_login_with_the_wrong_password_is_unauthorized() -> None:
    app, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "not the password"},
        )
    assert response.status_code == 401


def test_login_with_an_unregistered_email_is_unauthorized() -> None:
    app, _ = _app(rows=[])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "nobody@example.com", "password": "anything"},
        )
    assert response.status_code == 401


def test_login_with_the_right_password_returns_a_token() -> None:
    app, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "the real password"},
        )
    assert response.status_code == 200
    assert response.json()["token"]


def test_me_requires_a_valid_token() -> None:
    app, _ = _app()
    with TestClient(app) as client:
        response = client.get("/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_the_signed_in_account() -> None:
    app, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        login = client.post(
            "/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "the real password"},
        )
        token = login.json()["token"]
        response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "person@example.com"


def test_logout_makes_the_token_stop_working() -> None:
    app, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        login = client.post(
            "/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "the real password"},
        )
        token = login.json()["token"]
        logout = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        after = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 204
    assert after.status_code == 401


def test_signup_rejects_a_password_that_bcrypt_would_silently_truncate() -> None:
    app, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": ORIGIN},
            json={"email": "person@example.com", "password": "x" * 73},
        )
    assert response.status_code == 422
