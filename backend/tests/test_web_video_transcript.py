"""Tests for deterministic transcript parsing and precedence."""

from backend.schemas.browser import CaptionCandidate
from backend.services.video_download.web.transcript import (
    choose_supplied_transcript,
    parse_ttml,
    parse_webvtt_or_srt,
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

