"""What an OCR engine is to its callers: frames in, the text each one shows out.

Visual indexing depends on this interface rather than on Surya, so an engine can be swapped or
compared in the eval (VISUAL_UNDERSTANDING_PLAN.md §8) without touching the stage that stores
what it read. An engine returns blocks as it read them, in reading order; turning them into
the one piece of text a keyframe stores is `text.py`'s job and the same for every engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class OcrError(RuntimeError):
    """The engine could not read a batch of frames: it is not installed, crashed or timed out."""


@dataclass(frozen=True)
class TextBlock:
    """One block of text an engine read: a heading, a paragraph, a table, a line of code."""

    text: str
    # The engine's own name for the kind of block, e.g. `Text`, `SectionHeader`, `Table`.
    label: str
    # How sure the engine was of the block's text, 0-1; None when it does not say.
    confidence: float | None = None


@dataclass(frozen=True)
class FrameReading:
    """Everything one engine read on one frame, in reading order; no blocks when it saw no text."""

    blocks: tuple[TextBlock, ...] = ()


class OcrEngine(Protocol):
    """Reads the text shown on frames."""

    # Stored beside every keyframe it read, so text from an engine that proved unreliable can
    # be found and read again.
    name: str

    def read(self, images: Sequence[Image.Image]) -> list[FrameReading]:
        """One reading per image, in the same order. Raises `OcrError` when the batch fails."""
        ...
