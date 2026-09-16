"""Builds the connection pool the rest of the backend reaches PostgreSQL through.

This is what replaced talking to a database over HTTP. The row API this project used
before made every call a request, so there was nothing to pool and no way to group two
writes; a real driver means a connection is worth keeping open between jobs, and it means a
write that spans several statements can be one transaction.

Connections hand rows back as dictionaries rather than tuples, so the store modules read a
column by name and a column added by a later migration cannot shift what an existing one
means. `iso_text` lives here for the same reason: it is about what the driver hands back,
not about any one table.

Needs AZURE_DATABASE_URL in `backend/.env`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import PostgresSettings, load_postgres_settings

# The companion runs one job at a time on a single worker thread, so the pool exists to
# keep a connection warm between jobs rather than to serve concurrency. A small ceiling is
# still worth having: Azure's smaller tiers cap connections per server, and an idle
# companion should not hold several of them.
MIN_POOL_SIZE = 1
MAX_POOL_SIZE = 4

# How long a caller waits for a free connection before giving up. Reached only if every
# connection is busy, which on one worker thread means something is wedged.
POOL_TIMEOUT_SECONDS = 30.0

logger = logging.getLogger(__name__)


def build_pool(settings: PostgresSettings | None = None) -> ConnectionPool:
    """Open a connection pool against the configured database.

    `open=True` connects eagerly, so a wrong URL or a firewall that has not been told about
    this machine is reported here, by whoever asked for the pool, rather than on the first
    query somewhere deeper.
    """
    resolved = settings or load_postgres_settings()
    logger.info("Connecting to PostgreSQL at %s", resolved.host)
    return ConnectionPool(
        resolved.url,
        min_size=MIN_POOL_SIZE,
        max_size=MAX_POOL_SIZE,
        timeout=POOL_TIMEOUT_SECONDS,
        kwargs={"row_factory": dict_row},
        open=True,
    )


@lru_cache(maxsize=1)
def shared_pool() -> ConnectionPool:
    """The process-wide pool, so connections are reused across jobs.

    `build_pool` stays available for a test or a second database.
    """
    return build_pool()


@contextmanager
def connection(pool: ConnectionPool | None = None) -> Iterator:
    """One connection from the pool, as a transaction that commits or rolls back.

    psycopg leaves a connection in a transaction from the first statement onwards and
    commits it when the `connection()` block ends, so everything inside one `with` either
    lands together or not at all. That is what lets a store replace a video's whole
    transcript without it being briefly half-written.
    """
    with (pool or shared_pool()).connection() as open_connection:
        yield open_connection


def iso_text(value) -> str:
    """One timestamp column as an ISO 8601 string.

    The driver decodes `timestamptz` into a `datetime`, while the dataclasses these rows
    are read into carry the ISO string the source gave -- a YouTube publish time, or a row's
    own `created_at`. Converting here keeps the types the rest of the pipeline passes around
    unchanged. A value that is already text is left alone, since a test that supplies one
    means exactly what it wrote.
    """
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
