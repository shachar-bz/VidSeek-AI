"""Times an already-known transcript against a video, via ElevenLabs' hosted forced aligner.

Used as a fallback for a video whose text is already known — a page transcript, a caption
track with no timing — but which was never measured against the audio. Rather than throw
that text away and transcribe it from scratch, forced alignment fits the same words onto
the video's timeline in one request, no ffmpeg step and nothing temporary on disk, the same
way `backend.services.transcription.elevenlabs` reads Scribe's audio out of the container.

The model aligns whatever text it is given with no language check of its own, and is only
proven to work on English; `language.is_english_text` is what has to gate every call here.

Needs `ELEVENLABS_API_KEY_FORCED_ALIGNMENT` in `backend/.env` — a key of its own, kept apart
from `ELEVENLABS_API_KEY_TRANSCRIPT`, so alignment traffic is never billed or rate-limited
against the transcription key's own quota.
"""

import os
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError

from backend.core import config
from backend.services.transcription.elevenlabs.transcriber import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_MEDIA_SUFFIXES,
)

from .transcript import AlignedWord, ForcedAlignmentResult

API_KEY_NAME = "ELEVENLABS_API_KEY_FORCED_ALIGNMENT"

# The SDK retries 429, 408, 409 and every 5xx itself; everything else in the 4xx range
# fails immediately, which is what a bad key or an unreadable file deserves.
DEFAULT_MAX_RETRIES = 5

# Per attempt, covering the upload and the alignment that follows it. Left unbounded by the
# SDK otherwise, which turns a stalled connection into a hang with no end.
DEFAULT_TIMEOUT_SECONDS = 30 * 60.0

# Returned on a 429, which for this API means too many requests in flight at once rather
# than a spent quota.
TOO_MANY_REQUESTS_STATUS = 429


def _load_api_key() -> str:
    """Read the forced alignment key from `backend/.env`, falling back to the environment."""
    return config.require(API_KEY_NAME)


def build_client(timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> ElevenLabs:
    """Build an ElevenLabs client authenticated with this project's forced alignment key."""
    return ElevenLabs(api_key=_load_api_key(), timeout=timeout_seconds)


def _validate_media_file(media_path: str) -> None:
    """Reject a file the aligner is certain to refuse, before any of it is uploaded."""
    if not os.path.isfile(media_path):
        raise FileNotFoundError(f"Media not found: {media_path}")

    suffix = Path(media_path).suffix.lower()
    if suffix not in SUPPORTED_MEDIA_SUFFIXES:
        raise ValueError(
            f"Unsupported media container '{suffix}' for {media_path}. "
            f"Accepts: {', '.join(sorted(SUPPORTED_MEDIA_SUFFIXES))}"
        )

    size_bytes = os.path.getsize(media_path)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"{media_path} is {size_bytes / 1024**3:.1f} GB, over the "
            f"{MAX_UPLOAD_BYTES / 1024**3:.0f} GB per-request limit"
        )


def _describe_concurrency(error: ApiError) -> str:
    """Report how many requests were in flight when the API turned this one away."""
    headers = error.headers or {}
    names = ("current-concurrent-requests", "maximum-concurrent-requests")
    reported = [f"{name}={headers[name]}" for name in names if name in headers]
    return ", ".join(reported) if reported else "no concurrency headers returned"


def align_text_to_media(
    media_path: str,
    text: str,
    *,
    client: ElevenLabs | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ForcedAlignmentResult:
    """Time every word of `text` against the speech in `media_path`.

    This is not recognition: a word `text` does not contain can never appear in the
    result, and the model assumes every word in `text` really was spoken in `media_path`,
    in that order. Text lifted from somewhere other than this video's own audio — a
    mismatched transcript — will still return a result, just a wrong one.
    """
    _validate_media_file(media_path)
    client = client or build_client(timeout_seconds)

    try:
        with open(media_path, "rb") as media_file:
            response = client.forced_alignment.create(
                file=media_file,
                text=text,
                request_options={"max_retries": max_retries},
            )
    except ApiError as error:
        if error.status_code == TOO_MANY_REQUESTS_STATUS:
            raise RuntimeError(
                f"ElevenLabs refused {media_path} after {max_retries} retries: too many "
                f"requests in flight at once ({_describe_concurrency(error)}). This is a "
                f"concurrency ceiling, not a spent quota — align fewer videos in parallel."
            ) from error
        raise

    words = [
        AlignedWord(
            text=word.text, start_seconds=word.start, end_seconds=word.end, loss=word.loss
        )
        for word in response.words
    ]

    return ForcedAlignmentResult(media_path=media_path, text=text, loss=response.loss, words=words)
