"""Reads the Azure Database for PostgreSQL connection URL out of `backend/.env`.

The canonical name is `AZURE_DATABASE_URL`. `ASURE_DATABASE_URL` is accepted as well,
because that misspelling is what the project's own `.env` was first written with, and a
checkout that has it should connect rather than report a variable it appears to have set.

Nothing is read at import time. A machine with no database still runs every other service,
and only a call that actually touches Postgres fails, with a message naming the variable to
set.
"""

import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from backend.core import config

URL_NAME = "AZURE_DATABASE_URL"
MISSPELLED_URL_NAME = "ASURE_DATABASE_URL"

# The schemes libpq understands for a connection URI. `postgres://` is the older spelling
# of the same thing and is still accepted everywhere, so both are allowed here.
SUPPORTED_SCHEMES = {"postgresql", "postgres"}

# Azure Database for PostgreSQL refuses unencrypted connections outright, so a URL without
# this is a misconfiguration that would otherwise surface as a bare connection failure.
REQUIRED_SSL_MODES = {"require", "verify-ca", "verify-full"}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostgresSettings:
    """Everything needed to reach one PostgreSQL database."""

    url: str

    @property
    def host(self) -> str:
        """The server the URL points at, for log lines that should not carry a password."""
        return urlsplit(self.url).hostname or "(unknown host)"


def load_postgres_settings() -> PostgresSettings:
    """Collect the database settings, failing with the name of whatever is missing."""
    url = config.get(URL_NAME) or config.get(MISSPELLED_URL_NAME)
    if not url:
        raise RuntimeError(
            f"{URL_NAME} is not set in {config.ENV_PATH} or the environment"
        )
    return PostgresSettings(url=_connection_url(url))


def is_postgres_configured() -> bool:
    """Whether there is a database to talk to at all.

    A job asks this before recording anything, so that a checkout with no database still
    downloads, transcribes and uploads videos instead of failing at the last step.
    """
    return bool(config.get(URL_NAME) or config.get(MISSPELLED_URL_NAME))


def _connection_url(url: str) -> str:
    """Check the URL is one libpq will accept, and warn if it asks for no encryption.

    TLS is a warning rather than an error because it is the server that decides, not this
    code: Azure rejects a plaintext connection itself, and a local Postgres used for a test
    has no reason to be refused here.
    """
    trimmed = url.strip()
    parsed = urlsplit(trimmed)
    if parsed.scheme not in SUPPORTED_SCHEMES:
        raise RuntimeError(
            f"{URL_NAME} must be a postgresql:// connection URL, "
            f"not {parsed.scheme or 'a value with no scheme'}://"
        )
    if not parsed.hostname:
        raise RuntimeError(f"{URL_NAME} names no host; it must include the server to connect to")
    ssl_modes = parse_qs(parsed.query).get("sslmode") or []
    if not any(mode in REQUIRED_SSL_MODES for mode in ssl_modes):
        logger.warning(
            "%s carries no sslmode=require; Azure Database for PostgreSQL refuses "
            "unencrypted connections and will reject this URL",
            URL_NAME,
        )
    return trimmed
