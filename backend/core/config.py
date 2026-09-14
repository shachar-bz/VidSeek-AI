"""Reads the backend's configuration from `backend/.env` and the process environment.

This is the only module in the backend that opens the `.env` file. It used to be computed
as `Path(__file__).parent.parent / ".env"` in five separate modules, which made the file's
location depend on how deeply each caller happened to be nested; one of those five already
pointed at a path that does not exist and worked only by falling through to the
environment. `core` sits directly under `backend/`, so the path resolved here is correct
no matter where the caller lives.

The process environment wins over the file, so a value can be overridden in CI or in a
test without editing anyone's local `.env`.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_DIR / ".env"


@lru_cache(maxsize=1)
def _env_file_values() -> dict[str, str | None]:
    """Parse `.env` once per process; a missing file is simply an empty mapping."""
    return dict(dotenv_values(ENV_PATH))


def get(name: str, default: str | None = None) -> str | None:
    """Return a configuration value, preferring the environment over `.env`.

    An empty value counts as unset, so a variable left blank in `.env` behaves the same
    as one that was never written.
    """
    value = os.environ.get(name) or _env_file_values().get(name)
    return str(value) if value else default


def require(name: str) -> str:
    """Return a configuration value, or explain where to put it if it is missing.

    Raising at the point of use rather than at import time is deliberate: a service that
    never calls Firecrawl should still start on a machine with no FIRECRAWL_API_KEY.
    """
    value = get(name)
    if not value:
        raise RuntimeError(f"{name} is not set in {ENV_PATH} or the environment")
    return value


def download_root() -> Path:
    """The only filesystem root jobs may read from or write into."""
    configured = get("VIDSEEK_DOWNLOAD_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / "Downloads" / "VidSeek"


def extension_ids() -> set[str]:
    """The comma-separated allowlist of extension ids permitted to open a session."""
    raw_ids = get("VIDSEEK_EXTENSION_IDS") or ""
    return {item.strip() for item in raw_ids.split(",") if item.strip()}
