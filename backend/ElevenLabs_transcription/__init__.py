"""Public interface of the ElevenLabs transcription module."""

from .transcriber import (
    DEFAULT_SEED,
    MODEL,
    build_client,
    transcribe_video,
)
from .transcript import TranscriptAudioEvent, TranscriptionResult, TranscriptWord

__all__ = [
    "DEFAULT_SEED",
    "MODEL",
    "TranscriptAudioEvent",
    "TranscriptWord",
    "TranscriptionResult",
    "build_client",
    "transcribe_video",
]
