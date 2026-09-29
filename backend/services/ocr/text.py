"""Turns what an OCR engine read on one frame into the text, language and confidence a keyframe stores.

The blocks are joined in the engine's reading order, one per line, after dropping the ones the
engine was unsure of: text that is probably wrong costs more in search than no text, because a
trigram or e5 match on it sends the video agent to the wrong frame. The confidence kept is
the blocks' mean weighted by their length, so a long paragraph read well is not outvoted by a
misread page number.

The language is decided by script, from the letters alone: this layer is built for English and
Hebrew videos, so Latin script is taken to be English. Digits, punctuation and symbols count
for neither, so a Hebrew slide full of numbers is still `he`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .engine import FrameReading, TextBlock

# Blocks the engine gave less confidence than this are dropped. A starting value; the eval
# set tunes it.
MIN_BLOCK_CONFIDENCE = 0.5

# The values `video_keyframes_ocr_language_known` allows.
HEBREW = "he"
ENGLISH = "en"
MIXED = "mixed"
OTHER = "other"

# The share of a frame's letters one script needs for the frame to count as that language.
DOMINANT_SCRIPT_SHARE = 0.8

HEBREW_LETTER = re.compile(r"[א-תװ-ײ]")
LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
ANY_LETTER = re.compile(r"[^\W\d_]")
# Runs of spaces and tabs inside a line; line breaks are kept, since they separate blocks.
INLINE_WHITESPACE = re.compile(r"[ \t ]+")


@dataclass(frozen=True)
class OnScreenText:
    """The text one keyframe shows, as it is stored."""

    text: str
    language: str | None
    confidence: float | None


def on_screen_text(
    reading: FrameReading, *, min_block_confidence: float = MIN_BLOCK_CONFIDENCE
) -> OnScreenText | None:
    """The frame's text, or None when it shows none worth keeping."""
    kept = [
        (block, text)
        for block in reading.blocks
        if (text := _tidy(block.text))
        and (block.confidence is None or block.confidence >= min_block_confidence)
    ]
    if not kept:
        return None
    text = "\n".join(text for _, text in kept)
    return OnScreenText(text=text, language=script_language(text), confidence=_weighted_confidence(kept))


def script_language(text: str) -> str | None:
    """`he`, `en`, `mixed` or `other` by the letters the text is written in; None with no letters."""
    letters = len(ANY_LETTER.findall(text))
    if letters == 0:
        return None
    hebrew = len(HEBREW_LETTER.findall(text))
    latin = len(LATIN_LETTER.findall(text))
    if hebrew >= DOMINANT_SCRIPT_SHARE * letters:
        return HEBREW
    if latin >= DOMINANT_SCRIPT_SHARE * letters:
        return ENGLISH
    if hebrew and latin:
        return MIXED
    return OTHER


def _tidy(text: str) -> str:
    """The text with each line's spacing collapsed and empty lines dropped."""
    lines = (INLINE_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _weighted_confidence(kept: list[tuple[TextBlock, str]]) -> float | None:
    """The blocks' mean confidence weighted by length; None when no block reported one."""
    scored = [(block.confidence, len(text)) for block, text in kept if block.confidence is not None]
    total = sum(length for _, length in scored)
    if not total:
        return None
    return sum(confidence * length for confidence, length in scored) / total
