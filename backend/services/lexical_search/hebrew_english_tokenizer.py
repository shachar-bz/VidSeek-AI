"""`tokenize`: the terms of a Hebrew or English passage, the same rule for a query and a memory.

Lexical search only finds a memory when the query and the memory produce the *same* term, so
everything here is about making two spellings of one word collide, and nothing else:

* NFKC folds compatibility forms (full-width letters, ligatures, presentation forms of Hebrew
  letters) into their ordinary letters, and casefold makes "Python" and "PYTHON" one term.
* Niqqud and cantillation are stripped. Transcripts almost never carry them, but a typed query
  might, and a pointed word must still match the unpointed one.
* Geresh, gershayim and every quote that stands in for them are removed when they sit *inside*
  a word, so the acronym צה"ל, צה״ל and צה’ל all become צהל. Anywhere else they are just
  punctuation and separate words like any other.
* A term is a run of letters (any script) and digits. Everything else separates, including the
  point in "3.5", which becomes "3" and "5": a decimal number is rare in speech, both halves
  still match, and keeping the rule to "letters and digits" keeps it predictable.

There is no stemming and no stopword list. Over one video's few dozen memories BM25's IDF
already weighs words that are everywhere down to almost nothing, and a stemmer for Hebrew would
be a dependency and a source of surprises for a small gain.

What Hebrew does need is its one-letter prefixes: ו ה ב ל מ ש כ attach to the word, so
"בפייתון" ("in Python") would never meet "פייתון". Each Hebrew term starting with one of them
also yields itself without that letter. Only one letter is stripped: chains like "ובה" or
"וכשה" are accepted as misses, because stripping repeatedly turns ordinary words into
fragments (most Hebrew words start with one of these letters) and makes it hard to say what a
query will match. The variant must keep at least two letters, so short words like "בה" stay
whole. Both the original and the variant are emitted, original first, so a memory that says
"בפייתון" counts toward both terms. Final-form letters (ך ם ן ף ץ) are left as they are; a
prefix never touches the end of a word.
"""

from __future__ import annotations

import re
import unicodedata

# The letters that attach to the front of a Hebrew word as a prefix: and, the, in, to, from,
# that, as.
HEBREW_PREFIX_LETTERS = frozenset("והבלמשכ")
# A prefix variant shorter than this is more likely a fragment than a word.
MIN_LETTERS_AFTER_PREFIX = 2

_HEBREW_MARKS_FIRST = 0x0591
_HEBREW_MARKS_LAST = 0x05C7
_HEBREW_LETTER_RUN = re.compile(r"[א-ת]+")
# Geresh, gershayim, and the ASCII and typographic quotes typed in their place.
_ACRONYM_MARKS = "׳״'’‘\"“”"
# Letters only (word characters that are not digits or underscore) on both sides.
_ACRONYM_MARK_INSIDE_WORD = re.compile(rf"(?<=[^\W\d_])[{_ACRONYM_MARKS}]+(?=[^\W\d_])")
# A run of letters of any script and digits; underscore is a word character but not a letter.
_TERM = re.compile(r"[^\W_]+")


def tokenize(text: str) -> list[str]:
    """The terms of `text` in order, each Hebrew prefixed term followed by its unprefixed form."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = _without_hebrew_marks(normalized)
    normalized = _ACRONYM_MARK_INSIDE_WORD.sub("", normalized)
    terms: list[str] = []
    for term in _TERM.findall(normalized):
        terms.append(term)
        variant = _without_hebrew_prefix(term)
        if variant is not None:
            terms.append(variant)
    return terms


def _without_hebrew_marks(text: str) -> str:
    """`text` without niqqud and cantillation; Hebrew punctuation in the same block stays.

    The block U+0591–U+05C7 also holds maqaf, paseq and sof pasuq, which are punctuation rather
    than marks; they are kept so they separate words instead of gluing them together.
    """
    return "".join(
        character
        for character in text
        if not (
            _HEBREW_MARKS_FIRST <= ord(character) <= _HEBREW_MARKS_LAST
            and unicodedata.category(character).startswith("M")
        )
    )


def _without_hebrew_prefix(term: str) -> str | None:
    """`term` without its first letter if that letter is a Hebrew prefix, else None."""
    if not _HEBREW_LETTER_RUN.fullmatch(term) or term[0] not in HEBREW_PREFIX_LETTERS:
        return None
    variant = term[1:]
    return variant if len(variant) >= MIN_LETTERS_AFTER_PREFIX else None
