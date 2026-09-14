"""Reads the Supabase project URL and API key out of `backend/.env`.

Supabase hands out two keys for a project. The anon key is the one meant to ship inside a
browser and is governed entirely by row level security; the service role key bypasses RLS
and is meant for a server. This backend is a server, so `SUPABASE_SERVICE_ROLE_KEY` is
preferred and `SUPABASE_ANON_KEY` is the fallback, which is what a checkout that has only
ever configured the client-side key will find. Which of the two was used is carried on the
settings, so the client can say so once rather than leaving a caller to guess why every
write came back refused.

Nothing is read at import time. A machine with no Supabase project still runs every other
service, and only a call that actually touches the database fails, with a message naming
the variable to set.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core import config

URL_NAME = "SUPABASE_URL"
SERVICE_ROLE_KEY_NAME = "SUPABASE_SERVICE_ROLE_KEY"
ANON_KEY_NAME = "SUPABASE_ANON_KEY"


@dataclass(frozen=True)
class SupabaseSettings:
    """Everything needed to reach one Supabase project's REST API."""

    url: str
    api_key: str

    # False means the anon key is in use, and every table with RLS enabled and no anon
    # policy will refuse this connection. See `migrations/0001_videos.sql`.
    uses_service_role: bool


def load_supabase_settings() -> SupabaseSettings:
    """Collect the Supabase settings, failing with the name of whatever is missing."""
    service_role_key = config.get(SERVICE_ROLE_KEY_NAME)
    api_key = service_role_key or config.get(ANON_KEY_NAME)
    if not api_key:
        raise RuntimeError(
            f"{SERVICE_ROLE_KEY_NAME} (or {ANON_KEY_NAME}) "
            f"is not set in {config.ENV_PATH} or the environment"
        )
    return SupabaseSettings(
        url=_project_url(config.require(URL_NAME)),
        api_key=api_key,
        uses_service_role=bool(service_role_key),
    )


def is_supabase_configured() -> bool:
    """Whether there is a Supabase project to talk to at all.

    A job asks this before recording anything, so that a checkout with no Supabase
    credentials still downloads, transcribes and uploads videos instead of failing at the
    last step. Half a configuration counts as none: the missing half is then reported by
    `load_supabase_settings`, which names it.
    """
    return bool(config.get(URL_NAME)) and bool(
        config.get(SERVICE_ROLE_KEY_NAME) or config.get(ANON_KEY_NAME)
    )


def _project_url(url: str) -> str:
    """Reject anything that is not the bare project origin.

    The client appends `/rest/v1/...` itself, so a URL with a path already on it produces
    requests for `/rest/v1/rest/v1/...` that come back as a routing error rather than as
    the misconfiguration they are. A trailing slash is harmless enough to just remove.
    """
    trimmed = url.strip().rstrip("/")
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            f"{URL_NAME} must be the project URL, https://<project ref>.supabase.co"
        )
    if parsed.path:
        raise RuntimeError(
            f"{URL_NAME} must be the project URL alone (drop '{parsed.path}'); "
            "the REST path is added by the client"
        )
    return trimmed
