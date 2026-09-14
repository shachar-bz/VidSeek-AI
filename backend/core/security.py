"""Session tokens and the boundary guards applied before anything external is opened.

Everything here is generic: it validates a URL, a local path or a media file without
knowing which service asked. The one guard that is not generic — header filtering, which
reads a `BrowserContext` — lives with the web downloader instead, so that `core` never has
to import `backend.schemas`.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import config
from .errors import MissingDependencyError

SESSION_TTL_SECONDS = 30 * 60
SUPPORTED_LOCAL_MEDIA_SUFFIXES = frozenset(
    {
        ".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4",
        ".mpeg", ".mpg", ".ogg", ".webm", ".wmv",
    }
)


class SessionRegistry:
    """Issues short-lived bearer tokens bound to one allowed extension origin."""

    def __init__(self, allowed_extension_ids: set[str], ttl_seconds: int = SESSION_TTL_SECONDS):
        self._allowed_extension_ids = allowed_extension_ids
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "SessionRegistry":
        return cls(config.extension_ids())

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


def is_youtube_url(url: str) -> bool:
    """Whether `url` belongs to YouTube, including its mobile and music subdomains.

    This is the classifier the job router uses to choose a pipeline. It has to be decided
    on the server: the extension sends the page URL, and the companion cannot take the
    client's word for which pipeline should run.
    """
    hostname = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return (
        hostname == "youtu.be"
        or hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
        or hostname == "youtube-nocookie.com"
        or hostname.endswith(".youtube-nocookie.com")
    )


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
