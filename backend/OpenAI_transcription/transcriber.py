"""Transcribes a video's speech with OpenAI's `gpt-transcribe` model.

The model takes a little under an hour of audio per request and transcribes all of it, so
a typical video is one request and the result is one chunk covering the whole video. Only
a video longer than the ceiling is split, and then `chunk_planner` picks the split points.

Note that `gpt-transcribe` returns no timestamps at all: `verbose_json` and
`timestamp_granularities` are rejected for this model. Chunk boundaries are therefore the
only timing this module can produce, and word-level timing needs a separate alignment pass.

Needs `OPENAI_API_KEY_DUDU` in `backend/.env`, and the ffmpeg binary on PATH.
"""

import logging
import os
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

from .audio_extractor import AUDIO_SUFFIX, cut_audio, extracted_audio, read_duration_seconds
from .chunk_planner import detect_silence_intervals, plan_chunk_spans
from .transcript import TranscriptChunk, TranscriptionResult

MODEL = "gpt-transcribe"

# The languages this project's videos actually mix. `gpt-transcribe` accepts a list and
# code-switches within one request, so no separate language detection stage is needed.
DEFAULT_LANGUAGES = ("he", "en")

# Measured against Hebrew speech, not taken from the docs: 55 minutes in one request came
# back with 99.8% of the expected words, while 60.7 minutes was rejected outright. Requests
# at 4, 6, 8, 10, 12, 15, 25, 35, 45, 50 and 55 minutes all transcribed their audio in
# full, so the model does not silently truncate below the ceiling: it either answers
# completely or fails. 45 minutes leaves a wide margin under the shortest length that
# failed.
MAX_CHUNK_SECONDS = 45 * 60

ENV_FILENAME = ".env"
API_KEY_NAME = "OPENAI_API_KEY_DUDU"

# The SDK retries 429s and 5xx itself with exponential backoff, so the only thing left to
# choose here is how many times.
DEFAULT_MAX_RETRIES = 5

# How much of the previous chunk's transcript to hand the next one as context. Only used
# when a video is long enough to be split, where it keeps the spelling of names and terms
# from drifting between chunks and fragmenting a search index.
PROMPT_CONTEXT_CHARS = 600

# The reason `chunk_planner` reports for a split it could not place in silence.
HARD_CUT_REASON_PREFIX = "hard cut"

logger = logging.getLogger(__name__)


def _load_api_key() -> str:
    """Read the OpenAI key from `backend/.env`, falling back to the environment."""
    env_path = Path(__file__).resolve().parent.parent / ENV_FILENAME
    key = dotenv_values(env_path).get(API_KEY_NAME) or os.environ.get(API_KEY_NAME)
    if not key:
        raise RuntimeError(f"{API_KEY_NAME} is not set in {env_path} or the environment")
    return key


def build_client(max_retries: int = DEFAULT_MAX_RETRIES) -> OpenAI:
    """Build an OpenAI client authenticated with this project's key."""
    return OpenAI(api_key=_load_api_key(), max_retries=max_retries)


def transcribe_audio_file(
    audio_path: str,
    *,
    client: OpenAI | None = None,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    keywords: list[str] | None = None,
    prompt: str | None = None,
) -> tuple[str, list[str]]:
    """Transcribe one audio file in a single request, returning its text and its languages.

    `keywords` biases the model toward spellings it would otherwise get wrong: names,
    places and jargon. `prompt` carries the tail of the preceding chunk, so that a split
    transcript reads continuously across the seam.
    """
    client = client or build_client()
    options = {}
    if keywords:
        options["keywords"] = keywords
    if prompt:
        options["prompt"] = prompt

    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            file=audio_file, model=MODEL, languages=list(languages), **options
        )

    payload = response.model_dump()
    detected = [entry.get("code", "") for entry in (payload.get("languages") or [])]
    return payload.get("text", ""), [code for code in detected if code]


def _transcribe_span(
    audio_path: str,
    start_seconds: float,
    end_seconds: float,
    is_whole_file: bool,
    **transcribe_options,
) -> tuple[str, list[str]]:
    """Transcribe one planned span, cutting it out of the audio first unless it is all of it."""
    if is_whole_file:
        return transcribe_audio_file(audio_path, **transcribe_options)

    handle, span_path = tempfile.mkstemp(suffix=AUDIO_SUFFIX)
    os.close(handle)
    try:
        cut_audio(audio_path, span_path, start_seconds, end_seconds)
        return transcribe_audio_file(span_path, **transcribe_options)
    finally:
        try:
            os.remove(span_path)
        except OSError:
            pass


def transcribe_video(
    video_path: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    keywords: list[str] | None = None,
    shot_spans: list[tuple[float, float]] | None = None,
    max_chunk_seconds: float = MAX_CHUNK_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> TranscriptionResult:
    """Transcribe every word spoken in `video_path`.

    Videos shorter than `max_chunk_seconds`, which is nearly all of them, are sent in one
    request and come back as a single chunk spanning the whole video. Longer videos are
    split in silence, and passing `shot_spans` from either shot detection module lets those
    splits also land on a visual cut, where one happens to fall in the same pause.
    """
    client = build_client(max_retries)

    with extracted_audio(video_path) as audio_path:
        duration_seconds = read_duration_seconds(audio_path)

        needs_splitting = duration_seconds > max_chunk_seconds
        silence_intervals = detect_silence_intervals(audio_path) if needs_splitting else None
        spans = plan_chunk_spans(
            duration_seconds,
            max_chunk_seconds,
            silence_intervals=silence_intervals,
            shot_spans=shot_spans,
        )

        chunks: list[TranscriptChunk] = []
        previous_text = ""
        for index, (start_seconds, end_seconds, reason) in enumerate(spans):
            if reason.startswith(HARD_CUT_REASON_PREFIX):
                logger.warning(
                    "Splitting %s at %.1fs mid-speech: no silence found nearby. "
                    "A word may be lost at the seam.",
                    video_path,
                    start_seconds,
                )

            text, detected_languages = _transcribe_span(
                audio_path,
                start_seconds,
                end_seconds,
                is_whole_file=len(spans) == 1,
                client=client,
                languages=languages,
                keywords=keywords,
                prompt=previous_text[-PROMPT_CONTEXT_CHARS:] or None,
            )

            previous_text = text
            chunks.append(
                TranscriptChunk(
                    index=index,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    text=text,
                    languages=detected_languages,
                )
            )

    return TranscriptionResult(
        video_path=video_path,
        duration_seconds=duration_seconds,
        model=MODEL,
        chunks=chunks,
    )
