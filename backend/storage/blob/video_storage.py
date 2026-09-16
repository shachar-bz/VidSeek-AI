"""Stores video files in an Azure Blob Storage container, and hands out links to them.

This is the home of the actual media. A job downloads a video to VIDSEEK_DOWNLOAD_ROOT,
which is a scratch location on one machine, and uploading it here is what makes it outlive
that machine. Nothing else about a video -- its transcript, its comments, its job history --
belongs here; that is PostgreSQL's half.

Blobs are named `videos/<video_id>/<filename>`. Blob Storage has no directories, but it
treats `/` in a name as one for the purposes of listing, so everything about one video sits
under a prefix that can be listed or deleted as a unit, and two videos that happen to share
a filename cannot collide.

Needs AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_CONTAINER_NAME in `backend/.env`.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas

from .client import UPLOAD_CONCURRENCY, shared_client
from .settings import BlobSettings, load_blob_settings

NAME_PREFIX = "videos"

# The video containers this project actually produces, spelled out rather than left to
# `mimetypes`, which on Windows answers out of the registry and so gives a different type
# per machine for exactly these extensions -- and no type at all for .mkv.
CONTENT_TYPES_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".ts": "video/mp2t",
}

# What a container outside that map is stored as when `mimetypes` has no answer either.
# Left deliberately generic: claiming video/mp4 for an unrecognised file would mislead
# every later reader of the blob's metadata.
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# One hour, which comfortably outlives the click that follows a link and is short enough
# that a leaked URL stops working the same day.
DEFAULT_LINK_LIFETIME_SECONDS = 3600

# Anything outside this is replaced in a name segment. Blob Storage accepts far more, but a
# name that is safe in a URL, a log line and a shell argument is worth more than a faithful
# reproduction of whatever the page happened to title the video.
UNSAFE_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class StoredVideo:
    """One video file as it now exists in the container."""

    container: str
    name: str
    size_bytes: int
    content_type: str


def build_video_key(video_id: str, filename: str) -> str:
    """The blob name a video file is stored under."""
    return f"{NAME_PREFIX}/{_name_segment(video_id)}/{_name_segment(filename)}"


class BlobVideoStorage:
    """The video container, as the rest of the backend sees it."""

    def __init__(self, client=None, settings: BlobSettings | None = None):
        self._settings = settings or load_blob_settings()
        self._client = client if client is not None else shared_client()

    @property
    def container(self) -> str:
        return self._settings.container

    def upload_video(
        self,
        local_path: Path,
        *,
        video_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> StoredVideo:
        """Upload a downloaded video file, replacing whatever sits under the same name.

        Large files are staged as blocks and committed together, which the SDK arranges
        itself; the callback reports bytes uploaded out of the file's total, so that a job
        can turn it into progress.
        """
        size_bytes = local_path.stat().st_size
        content_type = guess_content_type(local_path)
        name = build_video_key(video_id, local_path.name)
        with local_path.open("rb") as video_file:
            self._blob(name).upload_blob(
                video_file,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
                max_concurrency=UPLOAD_CONCURRENCY,
                progress_hook=_byte_counter(size_bytes, progress_callback),
            )
        logger.info(
            "Uploaded %s to azure://%s/%s", local_path.name, self._settings.container, name
        )
        return StoredVideo(
            container=self._settings.container,
            name=name,
            size_bytes=size_bytes,
            content_type=content_type,
        )

    def download_video(self, name: str, destination: Path) -> Path:
        """Fetch a stored video back to disk, creating the destination's folder."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as video_file:
            self._blob(name).download_blob().readinto(video_file)
        return destination

    def video_exists(self, name: str) -> bool:
        return bool(self._blob(name).exists())

    def delete_video(self, name: str) -> None:
        """Remove a stored video. Deleting a blob that is not there is not an error."""
        try:
            self._blob(name).delete_blob()
        except ResourceNotFoundError:
            return

    def sas_download_url(
        self, name: str, expires_in_seconds: int = DEFAULT_LINK_LIFETIME_SECONDS
    ) -> str:
        """A temporary link to a stored video, usable without any credentials.

        This is how a video should normally be handed out: the container stays private, and
        the link expires on its own. It is signed with the account key, so the URL it
        returns is a credential for one blob for one hour and must not be logged or stored.
        """
        token = generate_blob_sas(
            account_name=self._settings.account_name,
            container_name=self._settings.container,
            blob_name=name,
            account_key=self._settings.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
        )
        return f"{self._blob(name).url}?{token}"

    def _blob(self, name: str):
        """The client for one blob in the configured container."""
        return self._client.get_blob_client(container=self._settings.container, blob=name)


def guess_content_type(local_path: Path) -> str:
    known = CONTENT_TYPES_BY_SUFFIX.get(local_path.suffix.lower())
    if known:
        return known
    content_type, _ = mimetypes.guess_type(local_path.name)
    return content_type or DEFAULT_CONTENT_TYPE


def _name_segment(value: str) -> str:
    """Reduce one path segment to characters that are safe everywhere a name travels."""
    safe = UNSAFE_NAME_CHARACTERS.sub("-", value.strip()).strip("-.")
    if not safe:
        raise ValueError(f"{value!r} has no characters usable in a blob name")
    return safe


def _byte_counter(
    total_bytes: int, progress_callback: ProgressCallback | None
) -> Callable[[int, int], None] | None:
    """Adapt the SDK's progress hook into the callback a job reports progress from.

    The SDK already accumulates across the threads a staged upload runs on, so the running
    total arrives ready to use. What it does not always know is the total: an upload from a
    file object reports `None` for it until the length is determined, and a progress bar
    cannot divide by that. The size measured before the upload started is used instead.
    """
    if progress_callback is None:
        return None

    def report(uploaded: int, total: int | None) -> None:
        progress_callback(min(uploaded, total_bytes), total or total_bytes)

    return report
