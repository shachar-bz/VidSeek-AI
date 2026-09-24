"""Public interface of the OCR module: the engine interface, the text a keyframe stores, and v1's engine."""

from .configured import configured_ocr_engine
from .engine import FrameReading, OcrEngine, OcrError, TextBlock
from .text import (
    ENGLISH,
    HEBREW,
    MIN_BLOCK_CONFIDENCE,
    MIXED,
    OTHER,
    OnScreenText,
    on_screen_text,
    script_language,
)

__all__ = [
    "ENGLISH",
    "HEBREW",
    "MIN_BLOCK_CONFIDENCE",
    "MIXED",
    "OTHER",
    "FrameReading",
    "OcrEngine",
    "OcrError",
    "OnScreenText",
    "TextBlock",
    "configured_ocr_engine",
    "on_screen_text",
    "script_language",
]
