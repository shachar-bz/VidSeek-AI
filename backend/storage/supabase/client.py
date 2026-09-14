"""Builds the Supabase client the rest of the backend talks to the database through.

The name of this package shadows the `supabase` distribution it imports, which is safe:
Python 3 resolves `from supabase import ...` against `sys.path` and never against a
sibling module, so the import below reaches the installed library. It is worth knowing
about, because an accidental `import supabase` written as a relative import would not.

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) in `backend/.env`.
"""

import logging
from functools import lru_cache

from supabase import Client, create_client

from .settings import SupabaseSettings, load_supabase_settings

logger = logging.getLogger(__name__)


def build_client(settings: SupabaseSettings | None = None) -> Client:
    """Return a Supabase client bound to the configured project."""
    resolved = settings or load_supabase_settings()
    if not resolved.uses_service_role:
        logger.warning(
            "Connecting to Supabase with the anon key; every table with row level "
            "security and no anon policy will refuse this connection. Set "
            "SUPABASE_SERVICE_ROLE_KEY for server-side access."
        )
    return create_client(resolved.url, resolved.api_key)


@lru_cache(maxsize=1)
def shared_client() -> Client:
    """The process-wide client, so that connections are pooled across jobs.

    The client wraps an httpx session, which is safe to share between threads once it is
    built; `build_client` stays available for a test or a second project.
    """
    return build_client()
