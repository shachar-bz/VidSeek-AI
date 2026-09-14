"""Public interface of the forced alignment module."""

from .aligner import API_KEY_NAME, align_text_to_media, build_client
from .language import is_english_text
from .transcript import AlignedWord, ForcedAlignmentResult

__all__ = [
    "API_KEY_NAME",
    "AlignedWord",
    "ForcedAlignmentResult",
    "align_text_to_media",
    "build_client",
    "is_english_text",
]
