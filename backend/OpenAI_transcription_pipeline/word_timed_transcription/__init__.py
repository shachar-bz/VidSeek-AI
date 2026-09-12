"""Public interface of the word-timed transcription pipeline."""

from .transcription_aligner import (
    MAX_ALIGNMENT_SECONDS,
    add_word_timestamps,
    transcribe_video_with_word_timestamps,
)

__all__ = [
    "MAX_ALIGNMENT_SECONDS",
    "add_word_timestamps",
    "transcribe_video_with_word_timestamps",
]
