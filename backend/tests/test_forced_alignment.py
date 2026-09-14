"""Tests for the forced alignment module's language gate and result shape."""

from backend.services.forced_alignment import AlignedWord, ForcedAlignmentResult, is_english_text
from backend.services.transcripts import normalize_words


def test_english_text_is_recognized() -> None:
    assert is_english_text(
        "This is an ordinary English sentence describing what happens in the video."
    )


def test_non_english_text_is_rejected() -> None:
    assert not is_english_text("שלום עולם זהו טקסט בעברית לגמרי וארוך מספיק לזיהוי")


def test_empty_text_is_not_english() -> None:
    assert not is_english_text("")
    assert not is_english_text("   ")


def test_aligned_words_normalize_like_any_other_timed_source() -> None:
    """Forced alignment's output has to feed the same normalizer every other source does."""
    result = ForcedAlignmentResult(
        media_path="video.mp4",
        text="hello there",
        loss=0.1,
        words=[
            AlignedWord(text="hello", start_seconds=0.0, end_seconds=0.5, loss=0.05),
            AlignedWord(text="there", start_seconds=0.5, end_seconds=1.0, loss=0.05),
        ],
    )
    normalized = normalize_words(result.words, source="forced_alignment", language="en")
    assert normalized is not None
    assert normalized.text == "hello there"
    assert normalized.segments[0].start_seconds == 0.0
    assert normalized.segments[-1].end_seconds == 1.0
