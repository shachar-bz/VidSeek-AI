"""Tests for deterministic transcript parsing and precedence."""

from pathlib import Path
from unittest.mock import patch

from backend.schemas.browser import CaptionCandidate
from backend.services.forced_alignment import AlignedWord, ForcedAlignmentResult
from backend.services.video_download.web.transcript import (
    TranscriptArtifact,
    align_supplied_transcript,
    choose_supplied_transcript,
    parse_ttml,
    parse_webvtt_or_srt,
    subtitle_file_language,
    transcript_from_subtitle_files,
)


def test_webvtt_parser_preserves_timing_and_removes_markup() -> None:
    segments = parse_webvtt_or_srt(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n<b>Hello</b> world\n\n"
    )
    assert len(segments) == 1
    assert segments[0].text == "Hello world"
    assert segments[0].start_seconds == 1.0
    assert segments[0].end_seconds == 2.5


def test_ttml_parser_reads_paragraph_cues() -> None:
    segments = parse_ttml(
        '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
        '<p begin="00:00:03.000" end="00:00:04.000">שלום</p>'
        "</div></body></tt>"
    )
    assert segments[0].text == "שלום"
    assert segments[0].start_seconds == 3.0


def test_active_caption_beats_visible_page_transcript() -> None:
    transcript = choose_supplied_transcript(
        [
            CaptionCandidate(
                text="This is a visible transcript long enough to pass the minimum length. " * 2,
                format="text",
                is_visible_transcript=True,
            ),
            CaptionCandidate(
                text="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSpoken caption\n\n",
                format="vtt",
                is_active=True,
            ),
        ]
    )
    assert transcript is not None
    assert transcript.source == "captions"
    assert transcript.text == "Spoken caption"


def _untimed_english_artifact() -> TranscriptArtifact:
    return TranscriptArtifact(
        source="page_transcript",
        text="This is an ordinary English transcript with no timing of its own.",
    )


def test_forced_alignment_times_an_untimed_english_transcript(tmp_path: Path) -> None:
    supplied = _untimed_english_artifact()
    aligned = ForcedAlignmentResult(
        media_path="video.mp4",
        text=supplied.text,
        loss=0.1,
        words=[
            AlignedWord(text=word, start_seconds=index, end_seconds=index + 1, loss=0.05)
            for index, word in enumerate(supplied.text.split())
        ],
    )
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media",
        return_value=aligned,
    ) as align:
        result = align_supplied_transcript(tmp_path / "video.mp4", supplied)

    align.assert_called_once_with(str(tmp_path / "video.mp4"), supplied.text)
    assert result is not None
    assert result.source == "forced_alignment"
    assert result.is_timed
    assert result.text == supplied.text


def test_forced_alignment_is_skipped_for_non_english_text(tmp_path: Path) -> None:
    supplied = TranscriptArtifact(
        source="page_transcript", text="שלום עולם זהו טקסט בעברית לגמרי וארוך מספיק לזיהוי"
    )
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media"
    ) as align:
        result = align_supplied_transcript(tmp_path / "video.mp4", supplied)

    align.assert_not_called()
    assert result is None


def test_forced_alignment_failure_falls_through_to_none(tmp_path: Path) -> None:
    supplied = _untimed_english_artifact()
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media",
        side_effect=RuntimeError("hosted API is down"),
    ):
        result = align_supplied_transcript(tmp_path / "video.mp4", supplied)

    assert result is None


def test_subtitle_file_language_is_read_from_the_yt_dlp_file_name() -> None:
    assert subtitle_file_language(Path("clip-abc123.he.vtt")) == "he"
    assert subtitle_file_language(Path("My.Talk-abc.en-US.srt")) == "en-US"
    # No language between the name and the extension, or something that is not one.
    assert subtitle_file_language(Path("clip.vtt")) is None
    assert subtitle_file_language(Path("Talk v2.5-abc.vtt")) is None


def test_downloaded_subtitle_file_keeps_its_language(tmp_path: Path) -> None:
    path = tmp_path / "clip.he.vtt"
    path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nשלום לכולם\n", encoding="utf-8")

    artifact = transcript_from_subtitle_files([path])

    assert artifact is not None and artifact.is_timed
    assert artifact.language == "he"
    assert artifact.normalized.language == "he"
