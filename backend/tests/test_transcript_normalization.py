"""Tests the one guarantee every video is supposed to leave the pipeline with.

Whatever transcribed a video, what comes out is a chronological list of segments, each
carrying a start, an end and the speech spoken between them, rendered as
`[MM:SS-MM:SS] text`. These tests hold that guarantee from both directions: the shapes the
real services return go in, and the same format comes out.
"""

import re
from pathlib import Path

from backend.db import transcript_store
from backend.services.transcription.elevenlabs import TranscriptWord
from backend.services.transcripts import (
    TimingFidelity,
    normalize_caption_cues,
    normalize_words,
)
from backend.services.video_download.web.transcript import CaptionSegment as WebCue
from backend.services.video_download.youtube.transcript import CaptionSegment as YouTubeCue

SEGMENT_LINE_PATTERN = re.compile(r"^\[\d{2}:\d{2}-\d{2}:\d{2}\] \S.*$")


def _cue(text: str, start: float, end: float) -> YouTubeCue:
    return YouTubeCue(text=text, start_seconds=start, end_seconds=end)


def _word(text: str, start: float, end: float) -> TranscriptWord:
    return TranscriptWord(
        text=text, start_seconds=start, end_seconds=end, speaker_id="speaker_0", logprob=-0.1
    )


def test_the_rendered_transcript_is_the_agreed_format() -> None:
    transcript = normalize_caption_cues(
        [
            _cue("Today I want to explain why most startups fail.", 0.0, 8.0),
            _cue("The first reason is that founders build something nobody wants.", 8.0, 17.0),
            _cue("We made this exact mistake in our first company.", 17.0, 28.0),
        ],
        source="youtube_captions",
    )

    assert transcript.formatted_text == (
        "[00:00-00:08] Today I want to explain why most startups fail.\n"
        "[00:08-00:17] The first reason is that founders build something nobody wants.\n"
        "[00:17-00:28] We made this exact mistake in our first company."
    )


def test_every_segment_is_timed_and_in_chronological_order() -> None:
    transcript = normalize_caption_cues(
        [
            _cue("one.", 12.0, 18.0),
            _cue("two.", 0.0, 6.0),
            _cue("three.", 30.0, 36.0),
        ],
        source="captions",
    )

    segments = transcript.segments
    assert [segment.index for segment in segments] == list(range(len(segments)))
    assert all(segment.end_seconds >= segment.start_seconds for segment in segments)
    assert all(
        later.start_seconds >= earlier.end_seconds
        for earlier, later in zip(segments, segments[1:])
    )
    # Cues arriving out of order are put in order rather than trusted.
    assert segments[0].text.startswith("two.")


def test_overlapping_cues_never_produce_overlapping_segments() -> None:
    """Automatic caption tracks scroll, and a cue routinely outlives the one after it."""
    transcript = normalize_caption_cues(
        [_cue("one.", 0.0, 20.0), _cue("two.", 5.0, 25.0)], source="captions"
    )

    first, second = transcript.segments
    assert first.end_seconds == 5.0
    assert second.start_seconds == 5.0


def test_a_cue_with_no_end_is_closed_at_the_next_cue_and_the_last_at_the_duration() -> None:
    """TTML cues can carry a begin and no end; neither gap is filled by guessing."""
    transcript = normalize_caption_cues(
        [WebCue(text="one.", start_seconds=0.0), WebCue(text="two.", start_seconds=6.0)],
        source="captions",
        media_duration_seconds=12.0,
    )

    assert [(segment.start_seconds, segment.end_seconds) for segment in transcript.segments] == [
        (0.0, 12.0)
    ]


def test_a_trailing_cue_with_nothing_to_close_it_is_given_a_reading_length() -> None:
    transcript = normalize_caption_cues(
        [_cue("one.", 0.0, 3.0), WebCue(text="two words here", start_seconds=10.0)],
        source="captions",
    )

    last = transcript.segments[-1]
    assert last.start_seconds == 10.0
    assert 11.0 < last.end_seconds < 11.5


def test_words_are_gathered_into_readable_segments_rather_than_one_per_line() -> None:
    words = [_word(f"word{index}", index * 0.4, index * 0.4 + 0.4) for index in range(12)]

    transcript = normalize_words(words, source="elevenlabs", language="en")

    assert transcript.timing_fidelity is TimingFidelity.WORD
    assert len(transcript.segments) == 1
    assert transcript.segments[0].start_seconds == 0.0
    assert transcript.segments[0].text.startswith("word0 word1")


def test_a_silence_ends_a_segment_where_the_speaker_stopped() -> None:
    transcript = normalize_words(
        [_word("one", 0.0, 1.0), _word("two", 1.0, 2.0), _word("three", 6.0, 7.0)],
        source="elevenlabs",
    )

    assert [segment.text for segment in transcript.segments] == ["one two", "three"]


def test_speech_that_never_pauses_is_still_broken_up() -> None:
    words = [_word(f"word{index}", index * 0.5, index * 0.5 + 0.5) for index in range(80)]

    transcript = normalize_words(words, source="elevenlabs")

    assert len(transcript.segments) > 1
    assert all(segment.duration_seconds <= 17.0 for segment in transcript.segments)


def test_text_with_no_timing_is_refused_rather_than_given_invented_timing() -> None:
    """The whole point of the contract: a timestamp is measured or it is not offered."""
    assert normalize_caption_cues([WebCue(text="a published transcript")], source="page") is None
    assert normalize_words([], source="elevenlabs") is None


def test_a_video_past_an_hour_stamps_every_line_the_same_width() -> None:
    transcript = normalize_caption_cues(
        [_cue("early.", 0.0, 5.0), _cue("late.", 3600.0, 3700.0)], source="captions"
    )

    lines = transcript.formatted_text.splitlines()
    assert lines[0].startswith("[00:00:00-00:00:05]")
    assert lines[-1].startswith("[01:00:00-01:01:40]")


def test_captions_and_words_produce_the_same_transcript_shape() -> None:
    """The point of the whole package: the next stage cannot tell which source ran."""
    from_captions = normalize_caption_cues(
        [_cue("hello there.", 0.0, 4.0)], source="youtube_captions"
    )
    from_words = normalize_words(
        [_word("hello", 0.0, 2.0), _word("there.", 2.0, 4.0)], source="elevenlabs"
    )

    assert from_captions.to_payload().keys() == from_words.to_payload().keys()
    for transcript in (from_captions, from_words):
        assert all(
            SEGMENT_LINE_PATTERN.match(line)
            for line in transcript.formatted_text.splitlines()
        )
    assert from_captions.formatted_text == from_words.formatted_text


def test_a_stored_transcript_reads_back_as_it_was_written(tmp_path: Path) -> None:
    transcript = normalize_caption_cues(
        [_cue("hello there.", 0.0, 4.0), _cue("second line.", 10.0, 16.0)],
        source="youtube_captions",
        language="en",
    )

    transcript_store.save("dQw4w9WgXcQ", transcript, root=tmp_path)
    restored = transcript_store.load("dQw4w9WgXcQ", root=tmp_path)

    assert restored == transcript
    assert transcript_store.load_formatted_text("dQw4w9WgXcQ", root=tmp_path) == (
        transcript.formatted_text
    )


def test_a_video_id_that_cannot_be_a_file_name_is_still_storable(tmp_path: Path) -> None:
    """Web downloads are named after the page title, which holds anything a site put there."""
    video_id = "הרצאה: מה קורה? (2024)"
    transcript = normalize_caption_cues([_cue("shalom.", 0.0, 4.0)], source="captions")

    transcript_store.save(video_id, transcript, root=tmp_path)

    assert transcript_store.load(video_id, root=tmp_path) == transcript
    assert transcript_store.video_ids(root=tmp_path) == [video_id]


def test_an_unknown_video_has_no_stored_transcript(tmp_path: Path) -> None:
    assert transcript_store.load("never-seen", root=tmp_path) is None
    assert transcript_store.video_ids(root=tmp_path) == []
