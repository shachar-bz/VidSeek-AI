"""Security boundaries for loopback sessions, URLs, headers, and local paths."""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .models import BrowserContext

SESSION_TTL_SECONDS = 30 * 60
ALLOWED_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "authorization", "origin", "referer", "user-agent"}
)
SUPPORTED_LOCAL_MEDIA_SUFFIXES = frozenset(
    {
        ".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4",
        ".mpeg", ".mpg", ".ogg", ".webm", ".wmv",
    }
)


class MissingDependencyError(RuntimeError):
    """A required external binary is not installed, so no job can ever succeed."""


class SessionRegistry:
    """Issues short-lived bearer tokens bound to one allowed extension origin."""

    def __init__(self, allowed_extension_ids: set[str], ttl_seconds: int = SESSION_TTL_SECONDS):
        self._allowed_extension_ids = allowed_extension_ids
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "SessionRegistry":
        return cls(configured_extension_ids())

    def is_allowed_origin(self, origin: str | None) -> bool:
        if not origin or not origin.startswith("chrome-extension://"):
            return False
        extension_id = origin.removeprefix("chrome-extension://").rstrip("/")
        return extension_id in self._allowed_extension_ids

    def create(self, origin: str | None) -> str:
        if not self.is_allowed_origin(origin):
            raise PermissionError(
                "Extension origin is not allowed; configure VIDSEEK_EXTENSION_IDS"
            )
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._tokens[token] = (origin or "", time.monotonic() + self._ttl_seconds)
        return token

    def verify(self, token: str, origin: str | None, *, require_origin: bool = True) -> bool:
        """Check a bearer token, and its origin whenever one is available.

        Chrome does not attach `Origin` to every request an extension makes, and a
        service worker polling job status over a host permission is one of the cases
        where it may be absent. An origin that is present must always match the one the
        token was issued to; `require_origin` is what decides whether a missing origin
        is fatal, so a read can proceed while anything that changes state cannot.
        """
        with self._lock:
            self._prune_locked()
            record = self._tokens.get(token)
            if not record:
                return False
            if origin is None:
                if require_origin:
                    return False
            elif record[0] != origin:
                return False
            self._tokens[token] = (record[0], time.monotonic() + self._ttl_seconds)
            return True

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, (_, expiry) in self._tokens.items() if expiry <= now]
        for token in expired:
            self._tokens.pop(token, None)


def configured_download_root() -> Path:
    """Return the only filesystem root jobs may read from or write into."""
    configured = _configuration_value("VIDSEEK_DOWNLOAD_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / "Downloads" / "VidSeek"


def _configuration_value(name: str) -> str | None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    value = os.environ.get(name) or dotenv_values(env_path).get(name)
    return str(value) if value else None


def configured_extension_ids() -> set[str]:
    """Read the comma-separated internal extension allowlist."""
    raw_ids = _configuration_value("VIDSEEK_EXTENSION_IDS") or ""
    return {item.strip() for item in raw_ids.split(",") if item.strip()}


def validate_remote_url(url: str) -> str:
    """Reject non-web and local-network targets before yt-dlp opens them."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP and HTTPS media URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("Credentials embedded in media URLs are not supported")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as error:
        raise ValueError("Media hostname could not be resolved") from error

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, loopback, and link-local media addresses are blocked")
    return url


def reject_youtube(url: str) -> None:
    """Keep YouTube owned by the project's dedicated YouTube module."""
    hostname = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if (
        hostname == "youtu.be"
        or hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
        or hostname == "youtube-nocookie.com"
        or hostname.endswith(".youtube-nocookie.com")
    ):
        raise ValueError("YouTube URLs must use the YouTube download pipeline")


def filtered_headers(
    context: BrowserContext,
    candidate_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Copy only request headers needed to reproduce a media request.

    Chrome's debugger reports header names lowercased, so names are folded to one
    canonical spelling here; otherwise a captured `user-agent` and the popup's own
    `User-Agent` would both be sent and yt-dlp would pick between them arbitrarily.
    """
    combined: dict[str, tuple[str, str]] = {}
    for name, value in {**context.headers, **(candidate_headers or {})}.items():
        combined[name.lower()] = (name, value)
    if context.user_agent:
        combined.setdefault("user-agent", ("User-Agent", context.user_agent))

    return {
        name: value
        for lowered, (name, value) in combined.items()
        if lowered in ALLOWED_REQUEST_HEADERS
        and "\r" not in value
        and "\n" not in value
    }


def validate_local_media_path(path_value: str, download_root: Path) -> Path:
    """Accept only an existing supported media file inside the configured root."""
    root = download_root.resolve()
    try:
        candidate = Path(path_value).resolve(strict=True)
    except OSError as error:
        raise ValueError("Chrome download path does not exist") from error
    if candidate.suffix.lower() not in SUPPORTED_LOCAL_MEDIA_SUFFIXES:
        raise ValueError("Chrome download is not a supported media file")
    if candidate == root or root not in candidate.parents:
        raise ValueError("Chrome download is outside VIDSEEK_DOWNLOAD_ROOT")
    if not candidate.is_file():
        raise ValueError("Chrome download path is not a file")
    probe_media_file(candidate)
    return candidate


def probe_media_file(path: Path) -> None:
    """Require ffprobe to recognize at least one actual video stream."""
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise MissingDependencyError(
            "ffprobe was not found on PATH; install FFmpeg to verify downloaded media"
        ) from error
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("Downloaded file is not valid media") from error
    streams = json.loads(process.stdout or "{}").get("streams") or []
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError("Downloaded file contains no video stream")
