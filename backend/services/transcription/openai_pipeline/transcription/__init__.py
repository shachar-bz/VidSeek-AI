"""Public interface of the OpenAI transcription module."""

from .audio_extractor import extract_audio, extracted_audio, read_duration_seconds
from .chunk_planner import detect_silence_intervals, plan_chunk_spans
from .transcriber import (
    MAX_CHUNK_SECONDS,
    MODEL,
    build_client,
    transcribe_audio_file,
    transcribe_video,
)
from .transcript import TranscriptChunk, TranscriptionResult, TranscriptWord

__all__ = [
    "MAX_CHUNK_SECONDS",
    "MODEL",
    "TranscriptChunk",
    "TranscriptWord",
    "TranscriptionResult",
    "build_client",
    "detect_silence_intervals",
    "extract_audio",
    "extracted_audio",
    "plan_chunk_spans",
    "read_duration_seconds",
    "transcribe_audio_file",
    "transcribe_video",
]
