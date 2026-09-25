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
LOCAL_WEBSITE_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


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
    never touches Blob Storage should still start on a machine with no
    AZURE_STORAGE_CONNECTION_STRING.
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


def website_origins() -> set[str]:
    """The comma-separated allowlist of VidSeek website origins, e.g. `https://app.vidseek.ai`.

    A user account signing in from the website is verified against this set rather than a
    Chrome extension id, so the two surfaces can be told apart without trusting anything the
    client says about itself. Local-companion mode admits the fixed Vite development origins
    by default; hosted mode remains closed until its origins are explicitly configured.
    """
    configured_origins = get("VIDSEEK_WEBSITE_ORIGINS")
    if configured_origins is None and require_loopback():
        return set(LOCAL_WEBSITE_ORIGINS)
    raw_origins = configured_origins or ""
    origins = {item.strip().rstrip("/") for item in raw_origins.split(",") if item.strip()}
    if "*" in origins:
        raise RuntimeError(
            "VIDSEEK_WEBSITE_ORIGINS must list explicit origins; '*' is not allowed"
        )
    return origins


def require_loopback() -> bool:
    """Whether the HTTP API accepts only clients on the loopback interface.

    The local companion keeps its historical protection by default. A hosted deployment
    explicitly opts out because its reverse proxy is not itself a loopback client.
    """
    raw_value = (get("VIDSEEK_REQUIRE_LOOPBACK", "true") or "true").strip().lower()
    if raw_value in {"true", "1", "yes", "on"}:
        return True
    if raw_value in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(
        "VIDSEEK_REQUIRE_LOOPBACK must be true or false "
        f"(received {raw_value!r})"
    )


def visual_indexing_enabled() -> bool:
    """Whether a stored video is indexed for what it shows, as well as for what is said.

    On by default. Indexing runs SigLIP 2 over every sampled frame, which is quick on the
    developer machine's GPU and slow on a CPU, so a machine without one can turn it off; its
    videos are then marked `skipped` rather than left looking queued.
    """
    raw_value = (get("VIDSEEK_VISUAL_INDEXING", "true") or "true").strip().lower()
    if raw_value in {"true", "1", "yes", "on"}:
        return True
    if raw_value in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(
        f"VIDSEEK_VISUAL_INDEXING must be true or false (received {raw_value!r})"
    )


def ocr_python_path() -> Path | None:
    """The Python interpreter of the separate environment Surya is installed in, or None.

    Surya needs a newer torch and an older Pillow than this backend runs on, so it cannot be
    installed next to it; on-screen text is read by a worker process started with this
    interpreter instead (`services/ocr/surya/`). Unset means OCR is off on
    this machine: videos are still indexed visually, and their keyframes are left unread.
    """
    configured = get("VIDSEEK_OCR_PYTHON")
    return Path(configured).expanduser() if configured else None


def ocr_llama_server_path() -> str | None:
    """Where llama.cpp's `llama-server` is, for Surya to run its OCR model with; None for PATH."""
    return get("VIDSEEK_OCR_LLAMA_SERVER")
