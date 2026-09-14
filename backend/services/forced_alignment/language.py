"""Whether a transcript's text is English, the only language forced alignment can align.

Forced alignment has no notion of language of its own: it fits whatever text it is given
onto whatever speech it hears, and a text in the wrong language just produces wrong timings
with no error to catch. This is the guard that has to run before the call, not after it.
"""

from langdetect import LangDetectException, detect

ENGLISH_LANGUAGE_CODE = "en"


def is_english_text(text: str) -> bool:
    """Whether `text`, taken as a whole, reads as English.

    Detection runs over the entire string rather than word by word, so a transcript that
    briefly quotes another language still counts as English as long as it reads as English
    overall; a transcript with too little text to classify, or none at all, does not.
    """
    stripped = text.strip()
    if not stripped:
        return False
    try:
        return detect(stripped) == ENGLISH_LANGUAGE_CODE
    except LangDetectException:
        return False
