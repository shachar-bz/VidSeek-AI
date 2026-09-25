"""Tests that the YouTube pipeline's result reaches the job manager in the shared shape."""

import threading
from pathlib import Path
from unittest.mock import patch

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.transcription.elevenlabs import TranscriptionResult, TranscriptWord
from backend.services.transcripts import normalize_caption_cues, normalize_words
from backend.services.video_download import youtube_job
from backend.services.video_download.youtube.comments import CommentEntry
from backend.services.video_download.youtube.pipeline import YouTubeDownloadResult
from backend.services.video_download.youtube.transcript import (
    CaptionSegment,
    YouTubeTranscript,
)


def _result(
    tmp_path: Path, transcript: YouTubeTranscript, comments_path, comments=None
) -> YouTubeDownloadResult:
    video_path = tmp_path / "abc.mp4"
    video_path.write_bytes(b"video")
    return YouTubeDownloadResult(
        url="https://youtu.be/abc",
        video_id="abc",
        title="A video",
        video_path=str(video_path),
        transcript=transcript,
        transcript_path=str(tmp_path / "abc.transcript.txt"),
        comments=comments or [],
        comments_path=comments_path,
    )


def _run(tmp_path: Path, result: YouTubeDownloadResult, **kwargs):
    with patch.object(youtube_job, "download_youtube_video", return_value=result) as download:
        pipeline_result = youtube_job.run_youtube_job(
            request=CreateVideoJobRequest(page_url="https://youtu.be/abc", **kwargs),
            download_root=tmp_path,
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )
    return pipeline_result, download


def test_caption_transcript_is_written_where_the_extension_looks(tmp_path: Path) -> None:
    segments = [CaptionSegment(text="hello there", start_seconds=0.0, end_seconds=1.5)]
    transcript = YouTubeTranscript(
        source="youtube_captions",
        text="hello there",
        segments=segments,
        normalized=normalize_caption_cues(segments, source="youtube_captions"),
    )
    result, _ = _run(tmp_path, _result(tmp_path, transcript, str(tmp_path / "abc.comments.json")))

    assert result.transcript_text_path == tmp_path / "abc.transcript.txt"
    assert result.transcript_json_path == tmp_path / "abc.transcript.json"
    # The written transcript is the normalized format, not the bare words, so a YouTube
    # video and a non-YouTube one leave the same thing on disk.
    assert result.transcript_text_path.read_text(encoding="utf-8") == "[00:00-00:02] hello there"
    # transcript_source passes through untranslated, so the extension sees what YouTube
    # actually supplied rather than a companion-invented label.
    assert result.transcript_source == "youtube_captions"
    assert result.transcript_error is None



def test_caption_transcript_keeps_the_track_language(tmp_path: Path) -> None:
    segments = [CaptionSegment(text="shalom", start_seconds=0.0, end_seconds=1.5)]
    transcript = YouTubeTranscript(
        source="youtube_captions",
        text="shalom",
        segments=segments,
        normalized=normalize_caption_cues(segments, source="youtube_captions", language="he"),
        language="he",
    )
    result, _ = _run(tmp_path, _result(tmp_path, transcript, None))

    assert result.normalized_transcript.language == "he"
    assert '"language": "he"' in result.transcript_json_path.read_text(encoding="utf-8")

def test_elevenlabs_transcript_keeps_its_language_and_full_result(tmp_path: Path) -> None:
    scribe = TranscriptionResult(
        video_path="abc.mp4",
        text="shalom",
        language_code="he",
        language_probability=0.9,
        duration_seconds=1.0,
        model="scribe_v1",
        words=[
            TranscriptWord(
                text="shalom",
                start_seconds=0.2,
                end_seconds=1.0,
                speaker_id="speaker_0",
                logprob=-0.1,
            )
        ],
    )
    transcript = YouTubeTranscript(
        source="elevenlabs",
        text="shalom",
        elevenlabs_result=scribe,
        normalized=normalize_words(scribe.words, source="elevenlabs", language="he"),
    )
    result, _ = _run(tmp_path, _result(tmp_path, transcript, None))

    assert result.transcript_source == "elevenlabs"
    assert result.transcript_error is None
    payload = result.transcript_json_path.read_text(encoding="utf-8")
    assert "shalom" in payload
    assert '"language": "he"' in payload


def test_a_transcript_with_no_timing_is_not_reported_as_a_finished_one(tmp_path: Path) -> None:
    """The text is kept, but a job that measured no timing has not met the contract."""
    transcript = YouTubeTranscript(source="youtube_captions", text="hello there")
    result, _ = _run(tmp_path, _result(tmp_path, transcript, None))

    assert result.transcript_text_path.read_text(encoding="utf-8") == "hello there"
    assert result.transcript_error == "untimed_transcript"


def test_the_video_is_downloaded_into_the_companion_root(tmp_path: Path) -> None:
    transcript = YouTubeTranscript(source="youtube_captions", text="x")
    _, download = _run(tmp_path, _result(tmp_path, transcript, None))
    assert download.call_args.kwargs["output_dir"] == tmp_path


def test_preferred_language_is_asked_for_before_english(tmp_path: Path) -> None:
    transcript = YouTubeTranscript(source="youtube_captions", text="x")
    _, download = _run(
        tmp_path, _result(tmp_path, transcript, None), preferred_language="he-IL"
    )
    assert download.call_args.kwargs["caption_languages"] == ("he-IL", "he", "en")


def test_a_missing_comments_file_is_reported_as_no_comments(tmp_path: Path) -> None:
    """A comments failure must not cost a job whose video and transcript both succeeded."""
    transcript = YouTubeTranscript(source="youtube_captions", text="x")
    result, _ = _run(tmp_path, _result(tmp_path, transcript, None))
    assert result.comments_path is None
    assert result.comments == ()
    assert result.video_path == tmp_path / "abc.mp4"
    assert result.transcript_text_path is not None


def test_fetched_comments_are_carried_through_rather_than_re_read_from_disk(
    tmp_path: Path,
) -> None:
    transcript = YouTubeTranscript(source="youtube_captions", text="x")
    comments = [
        CommentEntry(
            id="c1",
            author="A Viewer",
            text="nice video",
            like_count=3,
            reply_count=0,
            published_at="2026-09-14T10:00:00+00:00",
        )
    ]
    result, _ = _run(
        tmp_path,
        _result(tmp_path, transcript, str(tmp_path / "abc.comments.json"), comments=comments),
    )
    assert result.comments == tuple(comments)
