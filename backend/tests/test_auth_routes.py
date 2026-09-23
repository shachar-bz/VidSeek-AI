"""Tests for signup, login, /v1/auth/me, logout and session management."""

from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.core.auth import UserAuthRegistry, hash_password
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager
from backend.storage.postgres import PostgresSessions, PostgresUsers
from backend.tests.fake_postgres import FakePool

EXTENSION_ORIGIN = "chrome-extension://allowed"
WEBSITE_ORIGIN = "https://app.vidseek.example"
LOCAL_WEBSITE_ORIGIN = "http://localhost:5173"

ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "email": "person@example.com",
    "password_hash": hash_password("the real password"),
    "display_name": "Person",
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
}

SESSION_ROW = {
    "id": "22222222-3333-4444-5555-666666666666",
    "user_id": ROW["id"],
    "surface": "extension",
    "created_at": "2026-09-14T10:00:00+00:00",
    "last_used_at": "2026-09-14T10:00:00+00:00",
    "expires_at": "2026-09-21T10:00:00+00:00",
}


@pytest.fixture(autouse=True)
def configured_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route in this file checks `is_postgres_configured()` before touching the store."""
    monkeypatch.setenv(
        "AZURE_DATABASE_URL", "postgresql://u:p@host.postgres.database.azure.com:5432/db?sslmode=require"
    )


def _app(
    rows: list[dict] | None = None, sessions_pool: FakePool | None = None
) -> tuple[object, FakePool, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    session_pool = sessions_pool if sessions_pool is not None else FakePool(rows=[SESSION_ROW])
    durable_sessions = PostgresSessions(pool=session_pool)
    app = create_app(
        session_registry=SessionRegistry({"allowed"}),
        job_manager=JobManager(Path.cwd()),
        user_auth_registry=UserAuthRegistry(durable_sessions),
        users_store=PostgresUsers(pool=pool),
        sessions_store=durable_sessions,
    )
    return app, pool, session_pool


def _login(client: TestClient, origin: str = EXTENSION_ORIGIN) -> str:
    response = client.post(
        "/v1/auth/login",
        headers={"Origin": origin},
        json={"email": "person@example.com", "password": "the real password"},
    )
    return response.json()["token"]


def test_signup_from_a_disallowed_origin_is_refused() -> None:
    app, _, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": "https://malicious.example"},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 403


def test_signup_without_a_configured_database_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DATABASE_URL", raising=False)
    app, _, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 503


def test_signup_returns_a_token_and_the_new_account() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": EXTENSION_ORIGIN},
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
        user_auth_registry=UserAuthRegistry(PostgresSessions(pool=pool)),
        users_store=PostgresUsers(pool=pool),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "person@example.com", "password": "correct horse"},
        )
    assert response.status_code == 409
    assert "person@example.com" in response.json()["detail"]


def test_signup_from_a_configured_website_origin_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", WEBSITE_ORIGIN)
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": WEBSITE_ORIGIN},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 200


def test_signup_from_the_local_frontend_is_allowed_by_default() -> None:
    app, _, sessions_pool = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": LOCAL_WEBSITE_ORIGIN},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert response.status_code == 200
    assert sessions_pool.recorded[0].parameters[2] == "website"


def test_signing_up_from_the_website_records_the_website_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", WEBSITE_ORIGIN)
    app, _, sessions_pool = _app(rows=[ROW])
    with TestClient(app) as client:
        client.post(
            "/v1/auth/signup",
            headers={"Origin": WEBSITE_ORIGIN},
            json={"email": "a@example.com", "password": "correct horse"},
        )
    assert sessions_pool.recorded[0].parameters[2] == "website"


def test_a_client_supplied_surface_label_is_never_trusted() -> None:
    """`surface` is decided from `Origin`, not from anything the request body claims."""
    app, _, sessions_pool = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "a@example.com", "password": "correct horse", "surface": "website"},
        )
    assert response.status_code == 200
    assert sessions_pool.recorded[0].parameters[2] == "extension"


def test_login_with_the_wrong_password_is_unauthorized() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "person@example.com", "password": "not the password"},
        )
    assert response.status_code == 401


def test_login_with_an_unregistered_email_is_unauthorized() -> None:
    app, _, _ = _app(rows=[])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "nobody@example.com", "password": "anything"},
        )
    assert response.status_code == 401


def test_login_with_the_right_password_returns_a_token() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "person@example.com", "password": "the real password"},
        )
    assert response.status_code == 200
    assert response.json()["token"]


def test_login_from_a_configured_website_origin_returns_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDSEEK_WEBSITE_ORIGINS", WEBSITE_ORIGIN)
    app, _, sessions_pool = _app(rows=[ROW])
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            headers={"Origin": WEBSITE_ORIGIN},
            json={"email": "person@example.com", "password": "the real password"},
        )
    assert response.status_code == 200
    assert sessions_pool.recorded[0].parameters[2] == "website"


def test_me_requires_a_valid_token() -> None:
    app, _, _ = _app()
    with TestClient(app) as client:
        response = client.get("/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_the_signed_in_account() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        token = _login(client)
        response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "person@example.com"


def test_logout_makes_the_token_stop_working() -> None:
    sessions_pool = FakePool(
        responses=[
            [SESSION_ROW],  # login: sessions.create()
            [SESSION_ROW],  # logout: revoke()'s own verify() lookup
            [{"id": SESSION_ROW["id"]}],  # logout: the delete itself
            [],  # the /me call afterwards: the session is gone
        ]
    )
    app, _, _ = _app(rows=[ROW], sessions_pool=sessions_pool)
    with TestClient(app) as client:
        token = _login(client)
        logout = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        after = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 204
    assert after.status_code == 401


def test_signup_rejects_a_password_that_bcrypt_would_silently_truncate() -> None:
    app, _, _ = _app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/signup",
            headers={"Origin": EXTENSION_ORIGIN},
            json={"email": "person@example.com", "password": "x" * 73},
        )
    assert response.status_code == 422


def test_listing_sessions_marks_the_one_used_for_this_request() -> None:
    other_session = {**SESSION_ROW, "id": "44444444-5555-6666-7777-888888888888", "surface": "website"}
    sessions_pool = FakePool(rows=[SESSION_ROW, other_session])
    app, _, _ = _app(rows=[ROW], sessions_pool=sessions_pool)
    with TestClient(app) as client:
        token = _login(client)
        response = client.get("/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    by_id = {item["session_id"]: item for item in response.json()["sessions"]}
    assert by_id[SESSION_ROW["id"]]["current"] is True
    assert by_id[other_session["id"]]["current"] is False


def test_listing_sessions_requires_a_valid_token() -> None:
    app, _, _ = _app()
    with TestClient(app) as client:
        response = client.get("/v1/auth/sessions")
    assert response.status_code == 401


def test_revoking_the_session_used_for_this_request_succeeds() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        token = _login(client)
        response = client.delete(
            f"/v1/auth/sessions/{SESSION_ROW['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 204


def test_revoking_a_malformed_session_id_is_not_an_error() -> None:
    app, _, _ = _app(rows=[ROW])
    with TestClient(app) as client:
        token = _login(client)
        response = client.delete(
            "/v1/auth/sessions/not-a-real-session-id",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 204


def test_revoke_all_sessions_signs_out_every_surface() -> None:
    app, _, sessions_pool = _app(rows=[ROW])
    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/auth/sessions/revoke-all", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 204
    assert sessions_pool.statements[-1].startswith("delete from public.sessions where user_id")
    assert sessions_pool.recorded[-1].parameters == (SESSION_ROW["user_id"],)
