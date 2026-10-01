"""Tests that YouTube's WebVTT captions are read at the finest granularity they measured."""

from backend.services.transcripts import TimingFidelity
from backend.services.video_download.youtube.captions import parse_vtt

MANUAL_VTT = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello everyone, welcome to the show.

00:00:03.500 --> 00:00:07.000
Today we talk about testing.
"""

# Shaped like a real automatic track: each cue after the first repeats the previous cue's
# line once with no word stamps at all, then adds the new words with their own stamps.
AUTOMATIC_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.080 --> 00:00:02.280 align:start position:0%
so<00:00:00.400><c> today</c><00:00:00.640><c> we're</c><00:00:00.960><c> going</c><00:00:01.200><c> to</c><00:00:01.520><c> talk</c>

00:00:02.280 --> 00:00:02.290 align:start position:0%
so today we're going to talk

00:00:02.290 --> 00:00:05.360 align:start position:0%
so today we're going to talk
about<00:00:02.560><c> some</c><00:00:03.040><c> interesting</c><00:00:03.760><c> stuff</c>
"""

AUTOMATIC_VTT_WITHOUT_WORD_STAMPS = """WEBVTT

00:00:00.000 --> 00:00:03.000
Hello world, this automatic track carries no word stamps.
"""


def test_manual_captions_stay_at_cue_level() -> None:
    segments, timing_fidelity = parse_vtt(MANUAL_VTT, is_automatic=False)

    assert timing_fidelity is TimingFidelity.CAPTION
    assert [(segment.start_seconds, segment.end_seconds, segment.text) for segment in segments] == [
        (0.0, 3.5, "Hello everyone, welcome to the show."),
        (3.5, 7.0, "Today we talk about testing."),
    ]


def test_cues_with_no_blank_line_between_them_stay_separate() -> None:
    segments, _ = parse_vtt(MANUAL_VTT.replace("show.\n\n", "show.\n"), is_automatic=False)

    assert [(segment.start_seconds, segment.end_seconds, segment.text) for segment in segments] == [
        (0.0, 3.5, "Hello everyone, welcome to the show."),
        (3.5, 7.0, "Today we talk about testing."),
    ]


def test_automatic_captions_are_read_word_by_word() -> None:
    segments, timing_fidelity = parse_vtt(AUTOMATIC_VTT, is_automatic=True)

    assert timing_fidelity is TimingFidelity.WORD
    assert [segment.text for segment in segments] == [
        "so",
        "today",
        "we're",
        "going",
        "to",
        "talk",
        "about",
        "some",
        "interesting",
        "stuff",
    ]
    # The first word of a cue starts where the cue itself starts; a later word's own
    # `<...>` stamp gives it a more precise one.
    assert segments[0].start_seconds == 0.080
    assert segments[1].start_seconds == 0.400
    # A word's end borrows the next word's measured start...
    assert segments[0].end_seconds == segments[1].start_seconds
    # ...except the very last word, which has no next word and takes the last cue's end.
    assert segments[-1].end_seconds == 5.360
    # The duplicate, unstamped mid-track line contributes nothing on its own.
    assert sum(1 for segment in segments if segment.text == "so") == 1


def test_automatic_track_with_no_word_stamps_falls_back_to_cue_level() -> None:
    segments, timing_fidelity = parse_vtt(AUTOMATIC_VTT_WITHOUT_WORD_STAMPS, is_automatic=True)

    assert timing_fidelity is TimingFidelity.CAPTION
    assert len(segments) == 1
    assert segments[0].text == "Hello world, this automatic track carries no word stamps."
