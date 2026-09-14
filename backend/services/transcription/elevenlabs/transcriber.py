"""Transcribes a video's speech with ElevenLabs' Scribe v2 model.

One request does the whole job. The video file is uploaded as it is — Scribe reads the
audio track out of the container itself, so there is no ffmpeg step and nothing
temporary on disk — and comes back with the transcript, a timing and a speaker for every
word, and the non-speech sounds it heard. Up to 3 GB and 10 hours are accepted per
request, which covers any video this project will see, so the input is never split.

The request is synchronous, so what actually bounds a very long video is how long an HTTP
response can be held open, not the API's own ceiling. Scribe can deliver to a webhook
instead (`webhook=True`), which needs an endpoint to receive the result; that is the path
to take if hour-long videos ever become normal here.

Needs `ELEVENLABS_API_KEY_TRANSCRIPT` in `backend/.env`.
"""

import logging
import os
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError

from backend.core import config

from .transcript import TranscriptAudioEvent, TranscriptionResult, TranscriptWord

MODEL = "scribe_v2"

API_KEY_NAME = "ELEVENLABS_API_KEY_TRANSCRIPT"

# Pinned so that re-transcribing the same video returns the same text. Without a fixed
# seed the model samples differently each run, and then a diff between two runs cannot
# distinguish a real regression from ordinary nondeterminism. The value itself carries no
# meaning; only its being constant does.
DEFAULT_SEED = 20250912

# The SDK retries 429, 408, 409 and every 5xx itself, honouring `Retry-After` and falling
# back to exponential backoff with jitter, so the only thing left to choose here is how
# many times. Everything else in the 4xx range fails immediately, which is what a bad key
# or an unreadable file deserves.
DEFAULT_MAX_RETRIES = 5

# Per attempt, covering the upload and the transcription that follows it. The SDK leaves
# httpx with no timeout at all unless given one, which turns a stalled connection into a
# hang with no end; half an hour is far longer than any video in this project needs and
# still bounded.
DEFAULT_TIMEOUT_SECONDS = 30 * 60.0

# Containers Scribe accepts, from its documented audio/* and video/* media types. Checked
# before the upload starts, so an unsupported file fails in the first millisecond rather
# than after however long it takes to push it over the wire.
SUPPORTED_MEDIA_SUFFIXES = frozenset(
    {
        ".3gp",
        ".3gpp",
        ".aac",
        ".aif",
        ".aiff",
        ".avi",
        ".flac",
        ".flv",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wmv",
    }
)

# Scribe's documented per-request ceiling.
MAX_UPLOAD_BYTES = 3 * 1024**3

# The `type` tag on each entry of the response's `words` array. The third kind, `spacing`,
# is the whitespace between words and is dropped: indexing it yields empty search tokens.
WORD_ENTRY_TYPE = "word"
AUDIO_EVENT_ENTRY_TYPE = "audio_event"

# Returned on a 429, which for this API means too many requests in flight at once rather
# than a spent quota. Reading them says how far over the plan's ceiling a batch loop ran.
CONCURRENCY_HEADERS = ("current-concurrent-requests", "maximum-concurrent-requests")

TOO_MANY_REQUESTS_STATUS = 429

logger = logging.getLogger(__name__)


def _load_api_key() -> str:
    """Read the ElevenLabs key from `backend/.env`, falling back to the environment."""
    return config.require(API_KEY_NAME)


def build_client(timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> ElevenLabs:
    """Build an ElevenLabs client authenticated with this project's key."""
    return ElevenLabs(api_key=_load_api_key(), timeout=timeout_seconds)


def _validate_media_file(video_path: str) -> None:
    """Reject a file Scribe is certain to refuse, before any of it is uploaded."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    suffix = Path(video_path).suffix.lower()
    if suffix not in SUPPORTED_MEDIA_SUFFIXES:
        raise ValueError(
            f"Unsupported media container '{suffix}' for {video_path}. "
            f"Scribe accepts: {', '.join(sorted(SUPPORTED_MEDIA_SUFFIXES))}"
        )

    size_bytes = os.path.getsize(video_path)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"{video_path} is {size_bytes / 1024**3:.1f} GB, over Scribe's "
            f"{MAX_UPLOAD_BYTES / 1024**3:.0f} GB per-request limit"
        )


def _describe_concurrency(error: ApiError) -> str:
    """Report how many requests were in flight when the API turned this one away."""
    headers = error.headers or {}
    reported = [f"{name}={headers[name]}" for name in CONCURRENCY_HEADERS if name in headers]
    return ", ".join(reported) if reported else "no concurrency headers returned"


def _split_response_entries(
    entries,
) -> tuple[list[TranscriptWord], list[TranscriptAudioEvent]]:
    """Sort the response's one flat array into spoken words and tagged sounds.

    The array is not a list of words: each entry is tagged `word`, `spacing` or
    `audio_event`, and the three have to be told apart by that tag rather than by
    position. Spacing is whitespace and is dropped; an audio event is a sound nobody
    spoke and belongs beside the words, not among them.
    """
    words: list[TranscriptWord] = []
    audio_events: list[TranscriptAudioEvent] = []
    untimed_count = 0

    for entry in entries:
        if entry.type not in (WORD_ENTRY_TYPE, AUDIO_EVENT_ENTRY_TYPE):
            continue

        # Timing is optional in the response schema, and an entry without it cannot be
        # sought to, which is the whole point of keeping it. Asking for word granularity
        # means this should never happen, so say so rather than fail silently.
        if entry.start is None or entry.end is None:
            untimed_count += 1
            continue

        if entry.type == WORD_ENTRY_TYPE:
            words.append(
                TranscriptWord(
                    text=entry.text,
                    start_seconds=entry.start,
                    end_seconds=entry.end,
                    speaker_id=entry.speaker_id,
                    logprob=entry.logprob,
                )
            )
        else:
            audio_events.append(
                TranscriptAudioEvent(
                    label=entry.text, start_seconds=entry.start, end_seconds=entry.end
                )
            )

    if untimed_count:
        logger.warning(
            "Dropped %d transcript entries that came back without timestamps", untimed_count
        )

    return words, audio_events


def transcribe_video(
    video_path: str,
    *,
    language_code: str | None = None,
    num_speakers: int | None = None,
    diarize: bool = True,
    tag_audio_events: bool = True,
    seed: int = DEFAULT_SEED,
    client: ElevenLabs | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> TranscriptionResult:
    """Transcribe every word spoken in `video_path`.

    `language_code` is left unset by default so Scribe detects the language itself, which
    is what lets one call handle both the Hebrew and the English videos here; the result
    carries the language it settled on and how sure it was. Set it, as ISO-639-1 or
    ISO-639-3, only when the language is already known from the video's metadata.

    `num_speakers` is likewise a hint, not a requirement: leaving it unset lets Scribe
    decide, and setting it when the number really is known sharpens who-said-what.

    The text comes back in logical order, the order the words are spoken, which for
    Hebrew is not the order they are drawn. It is stored exactly that way and reversed
    for display at render time — bake visual order into a stored transcript and every
    Hebrew search query quietly stops matching it.
    """
    _validate_media_file(video_path)
    client = client or build_client(timeout_seconds)

    try:
        with open(video_path, "rb") as video_file:
            response = client.speech_to_text.convert(
                file=video_file,
                model_id=MODEL,
                language_code=language_code,
                diarize=diarize,
                num_speakers=num_speakers,
                tag_audio_events=tag_audio_events,
                timestamps_granularity="word",
                seed=seed,
                request_options={"max_retries": max_retries},
            )
    except ApiError as error:
        if error.status_code == TOO_MANY_REQUESTS_STATUS:
            raise RuntimeError(
                f"ElevenLabs refused {video_path} after {max_retries} retries: too many "
                f"requests in flight at once ({_describe_concurrency(error)}). This is a "
                f"concurrency ceiling, not a spent quota — transcribe fewer videos in "
                f"parallel."
            ) from error
        raise

    words, audio_events = _split_response_entries(response.words)

    return TranscriptionResult(
        video_path=video_path,
        text=response.text,
        language_code=response.language_code,
        language_probability=response.language_probability,
        # Scribe reports the duration it actually heard. Deriving it from the last word
        # instead would cut off wherever the video stops being speech.
        duration_seconds=response.audio_duration_secs or 0.0,
        model=MODEL,
        words=words,
        audio_events=audio_events,
    )
