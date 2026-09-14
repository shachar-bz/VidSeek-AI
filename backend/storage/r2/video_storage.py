"""Stores video files in a Cloudflare R2 bucket, and hands out links to them.

This is the home of the actual media. A job downloads a video to
VIDSEEK_DOWNLOAD_ROOT, which is a scratch location on one machine, and uploading it here
is what makes it outlive that machine. Nothing else about a video — its transcript, its
comments, its job history — belongs in R2; that is Supabase's half, and is not wired up
yet.

Objects are keyed `videos/<video_id>/<filename>`, so that everything about one video sits
under a prefix that can be listed or deleted as a unit, and so that two videos that
happen to share a filename cannot collide.

Needs R2_ACCESS_KEY_ID, R2_ACCESS_KEY, R2_ENDPOINT_URL and R2_BUCKET_NAME in
`backend/.env`.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from .client import MULTIPART_CHUNK_BYTES, shared_client
from .settings import R2Settings, load_r2_settings

KEY_PREFIX = "videos"

# The video containers this project actually produces, spelled out rather than left to
# `mimetypes`, which on Windows answers out of the registry and so gives a different type
# per machine for exactly these extensions — and no type at all for .mkv.
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
# every later reader of the object's metadata.
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# One hour, which comfortably outlives the click that follows a link and is short enough
# that a leaked URL stops working the same day.
DEFAULT_LINK_LIFETIME_SECONDS = 3600

# Anything outside this is replaced in a key segment. R2 accepts far more, but a key that
# is safe in a URL, a log line and a shell argument is worth more than a faithful
# reproduction of whatever the page happened to title the video.
UNSAFE_KEY_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")

logger = logging.getLogger(__name__)

# Reported by the S3 API when an object or a bucket is not there. `head_object` answers
# with the bare HTTP status, while other calls give the named code, so both are treated
# as absence.
NOT_FOUND_CODES = {"404", "NoSuchKey", "NoSuchBucket"}

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class StoredVideo:
    """One video file as it now exists in the bucket."""

    bucket: str
    key: str
    size_bytes: int
    content_type: str


def build_video_key(video_id: str, filename: str) -> str:
    """The object key a video file is stored under."""
    return f"{KEY_PREFIX}/{_key_segment(video_id)}/{_key_segment(filename)}"


class R2VideoStorage:
    """The video bucket, as the rest of the backend sees it."""

    def __init__(self, client=None, settings: R2Settings | None = None):
        self._settings = settings or load_r2_settings()
        self._client = client if client is not None else shared_client()

    @property
    def bucket(self) -> str:
        return self._settings.bucket

    def upload_video(
        self,
        local_path: Path,
        *,
        video_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> StoredVideo:
        """Upload a downloaded video file, replacing whatever sits under the same key.

        Large files are sent as a multipart upload, which boto3 arranges itself; the
        callback reports bytes uploaded out of the file's total, so that a job can turn
        it into progress.
        """
        size_bytes = local_path.stat().st_size
        content_type = guess_content_type(local_path)
        key = build_video_key(video_id, local_path.name)
        self._client.upload_file(
            str(local_path),
            self._settings.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
            Config=TransferConfig(
                multipart_threshold=MULTIPART_CHUNK_BYTES,
                multipart_chunksize=MULTIPART_CHUNK_BYTES,
            ),
            Callback=_byte_counter(size_bytes, progress_callback),
        )
        logger.info("Uploaded %s to r2://%s/%s", local_path.name, self._settings.bucket, key)
        return StoredVideo(
            bucket=self._settings.bucket,
            key=key,
            size_bytes=size_bytes,
            content_type=content_type,
        )

    def download_video(self, key: str, destination: Path) -> Path:
        """Fetch a stored video back to disk, creating the destination's folder."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._settings.bucket, key, str(destination))
        return destination

    def video_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._settings.bucket, Key=key)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True

    def delete_video(self, key: str) -> None:
        """Remove a stored video. Deleting an object that is not there is not an error."""
        self._client.delete_object(Bucket=self._settings.bucket, Key=key)

    def presigned_download_url(
        self, key: str, expires_in_seconds: int = DEFAULT_LINK_LIFETIME_SECONDS
    ) -> str:
        """A temporary link to a stored video, usable without any credentials.

        This is how a video should normally be handed out: the bucket stays private, and
        the link expires on its own.
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._settings.bucket, "Key": key},
            ExpiresIn=expires_in_seconds,
        )


def guess_content_type(local_path: Path) -> str:
    known = CONTENT_TYPES_BY_SUFFIX.get(local_path.suffix.lower())
    if known:
        return known
    content_type, _ = mimetypes.guess_type(local_path.name)
    return content_type or DEFAULT_CONTENT_TYPE


def _key_segment(value: str) -> str:
    """Reduce one path segment to characters that are safe everywhere a key travels."""
    safe = UNSAFE_KEY_CHARACTERS.sub("-", value.strip()).strip("-.")
    if not safe:
        raise ValueError(f"{value!r} has no characters usable in an object key")
    return safe


def _byte_counter(
    total_bytes: int, progress_callback: ProgressCallback | None
) -> Callable[[int], None] | None:
    """Adapt boto3's per-chunk callback into one that reports the running total.

    boto3 reports each chunk's size as it completes, which on a multipart upload arrives
    out of order and from several threads; summing here is what turns that into the
    monotonic "bytes so far" a progress bar needs.
    """
    if progress_callback is None:
        return None
    uploaded = 0

    def report(chunk_bytes: int) -> None:
        nonlocal uploaded
        uploaded += chunk_bytes
        progress_callback(min(uploaded, total_bytes), total_bytes)

    return report


def _is_not_found(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code")) in NOT_FOUND_CODES
