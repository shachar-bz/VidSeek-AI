"""Tests that YouTube captions with no usable timing fall back to ElevenLabs.

`fetch_captions` is only ever supposed to hand back segments that already carry real
timing, but `_build_transcript` should not rely on that invariant holding forever — a
caption track it cannot place in time must be treated the same as no captions at all.
"""

from pathlib import Path
from unittest.mock import patch

from backend.services.transcription.elevenlabs import TranscriptionResult, TranscriptWord
from backend.services.transcripts import TimingFidelity
from backend.services.video_download.youtube import pipeline
from backend.services.video_download.youtube.captions import FetchedCaptions
from backend.services.video_download.youtube.transcript import CaptionSegment


def _elevenlabs_result() -> TranscriptionResult:
    return TranscriptionResult(
        video_path="abc.mp4",
        text="hi there",
        language_code="en",
        language_probability=0.9,
        duration_seconds=1.0,
        model="scribe_v2",
        words=[
            TranscriptWord(
                text="hi there", start_seconds=0.0, end_seconds=0.5, speaker_id=None, logprob=-0.1
            )
        ],
    )


def test_a_caption_track_with_no_placeable_text_still_gets_transcribed() -> None:
    """A blank-text cue normalizes to nothing, so it must not win over ElevenLabs."""
    untimed = FetchedCaptions(
        segments=[CaptionSegment(text="   ", start_seconds=0.0, end_seconds=1.0)],
        timing_fidelity=TimingFidelity.CAPTION,
    )

    with (
        patch.object(pipeline, "fetch_captions", return_value=untimed),
        patch.object(pipeline, "transcribe_video", return_value=_elevenlabs_result()) as transcribe,
    ):
        transcript = pipeline._build_transcript(
            "abc.mp4", "https://youtu.be/abc", Path("out"), ("en",)
        )

    transcribe.assert_called_once_with("abc.mp4")
    assert transcript.source == "elevenlabs"
    assert transcript.is_timed


def test_a_normally_timed_caption_track_is_used_as_is() -> None:
    """The guard must not change behaviour for the ordinary, already-timed case."""
    fetched = FetchedCaptions(
        segments=[CaptionSegment(text="hello there", start_seconds=0.0, end_seconds=1.5)],
        timing_fidelity=TimingFidelity.CAPTION,
    )

    with (
        patch.object(pipeline, "fetch_captions", return_value=fetched),
        patch.object(pipeline, "transcribe_video") as transcribe,
    ):
        transcript = pipeline._build_transcript(
            "abc.mp4", "https://youtu.be/abc", Path("out"), ("en",)
        )

    transcribe.assert_not_called()
    assert transcript.source == "youtube_captions"
    assert transcript.is_timed


def test_the_caption_track_language_reaches_the_transcript() -> None:
    """The track's language is what `videos.transcript_language` is later written from."""
    fetched = FetchedCaptions(
        segments=[CaptionSegment(text="שלום לכולם", start_seconds=0.0, end_seconds=1.5)],
        timing_fidelity=TimingFidelity.CAPTION,
        language="he",
    )

    with patch.object(pipeline, "fetch_captions", return_value=fetched):
        transcript = pipeline._build_transcript(
            "abc.mp4", "https://youtu.be/abc", Path("out"), ("he", "en")
        )

    assert transcript.language == "he"
    assert transcript.normalized.language == "he"


def test_the_scribe_language_reaches_the_transcript() -> None:
    with (
        patch.object(pipeline, "fetch_captions", return_value=None),
        patch.object(pipeline, "transcribe_video", return_value=_elevenlabs_result()),
    ):
        transcript = pipeline._build_transcript(
            "abc.mp4", "https://youtu.be/abc", Path("out"), ("en",)
        )

    assert transcript.language == "en"
    assert transcript.normalized.language == "en"
