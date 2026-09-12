"""Turns a mixed Hebrew/English transcript into the romanized tokens the MMS aligner reads.

The MMS forced aligner has a 28-character vocabulary: lowercase a-z, an apostrophe, and a
star. Hebrew script, punctuation, niqqud and digits all have to be rendered into that
alphabet before a word can be aligned, and this module does it while remembering which
original word each piece came from, so that the timings come back attached to the Hebrew.

Two conversions matter here. Digits are spelled out in the language they are spoken in,
because `25` is one written token but two spoken words and aligning it as one would steal
time from its neighbours. Everything else is romanized with uroman, which maps Hebrew and
Latin script into one alphabet so that a sentence that switches between them aligns as a
single sequence.

Note that uroman transliterates unvocalized Hebrew letter by letter, so `מדינת` becomes
`mdynt` rather than the spoken `medinat`. The consonant skeleton is what anchors the
alignment; the vowels the speaker actually pronounces are absorbed into neighbouring
frames.
"""

import functools
import re
import unicodedata
from dataclasses import dataclass, field

import uroman
from num2words import num2words

# The aligner's whole alphabet, minus the blank and star tokens it inserts itself.
ALIGNABLE_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz'")

HEBREW_LETTERS = re.compile(r"[א-ת]")
# Niqqud, cantillation marks and the like: pronunciation aids written under and over the
# letters, which uroman would otherwise try to romanize.
HEBREW_DIACRITICS = re.compile(r"[֑-ׇ]")
# Maqaf is Hebrew's hyphen and joins two words into one written token, so it separates
# rather than disappears.
WORD_JOINING_PUNCTUATION = re.compile(r"[־\-‐-―/]")
DIGIT_RUN = re.compile(r"\d[\d,.]*\d|\d")

# num2words language codes for the two languages this project's videos mix.
HEBREW_NUMBER_LANGUAGE = "he"
ENGLISH_NUMBER_LANGUAGE = "en"

# uroman language code for Hebrew, which picks its Hebrew-specific romanization rules.
HEBREW_UROMAN_CODE = "heb"


@dataclass(frozen=True)
class NormalizedWord:
    """One word of the original transcript, and the romanized pieces it aligns as.

    A word normalizes to more than one piece when it contains a number that is spoken as
    several words, and to none at all when nothing in it is alignable — a lone ellipsis,
    an emoji, a bare symbol. Those keep their place in the list so that the caller can
    still hand back a timing for them.
    """

    index: int
    original: str
    romanized: list[str] = field(default_factory=list)

    @property
    def is_alignable(self) -> bool:
        return bool(self.romanized)


@functools.lru_cache(maxsize=1)
def _romanizer() -> uroman.Uroman:
    """Load uroman once: it reads its romanization tables from disk on construction."""
    return uroman.Uroman()


def _is_hebrew(text: str) -> bool:
    return HEBREW_LETTERS.search(text) is not None


def dominant_number_language(text: str) -> str:
    """Which language a bare number in this text is most likely spoken in.

    A word like `25` carries no script of its own, so the surrounding transcript decides.
    """
    return HEBREW_NUMBER_LANGUAGE if _is_hebrew(text) else ENGLISH_NUMBER_LANGUAGE


def _spell_number(digits: str, language: str) -> str:
    """Spell a run of digits as it would be spoken, or return it unchanged if that fails."""
    cleaned = digits.replace(",", "")
    try:
        number = float(cleaned) if "." in cleaned else int(cleaned)
        return num2words(number, lang=language)
    except (ValueError, NotImplementedError, OverflowError, IndexError):
        # num2words has gaps in its non-English locales; an unspellable number is better
        # left to be dropped and interpolated than allowed to fail the whole alignment.
        return ""


def _expand_numbers(word: str, number_language: str) -> str:
    """Replace every run of digits in a word with the words it is spoken as."""
    language = HEBREW_NUMBER_LANGUAGE if _is_hebrew(word) else number_language
    return DIGIT_RUN.sub(lambda match: f" {_spell_number(match.group(), language)} ", word)


def _to_alignable_pieces(word: str) -> list[str]:
    """Romanize one original word into the alignable pieces it is spoken as."""
    stripped = HEBREW_DIACRITICS.sub("", unicodedata.normalize("NFC", word))
    stripped = WORD_JOINING_PUNCTUATION.sub(" ", stripped)
    if not stripped.strip():
        return []

    lcode = HEBREW_UROMAN_CODE if _is_hebrew(stripped) else None
    romanized = _romanizer().romanize_string(stripped, lcode=lcode) if lcode else \
        _romanizer().romanize_string(stripped)

    pieces = []
    for piece in romanized.lower().split():
        kept = "".join(character for character in piece if character in ALIGNABLE_CHARACTERS)
        if kept:
            pieces.append(kept)
    return pieces


def normalize_words(words: list[str], *, number_language: str | None = None) -> list[NormalizedWord]:
    """Normalize a list of transcript words, keeping each one's place in the list."""
    if number_language is None:
        number_language = dominant_number_language(" ".join(words))

    normalized = []
    for index, word in enumerate(words):
        expanded = _expand_numbers(word, number_language)
        normalized.append(
            NormalizedWord(index=index, original=word, romanized=_to_alignable_pieces(expanded))
        )
    return normalized


def normalize_text(text: str, *, number_language: str | None = None) -> list[NormalizedWord]:
    """Split a transcript on whitespace and normalize each word."""
    return normalize_words(text.split(), number_language=number_language)
