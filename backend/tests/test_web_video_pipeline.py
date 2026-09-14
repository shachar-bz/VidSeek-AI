"""Tests what the pipeline guarantees about the transcript it produces.

Two promises, and they pull against each other. A transcript problem must never cost
the user the video that was already downloaded, and a transcript handed on as finished
must carry the timing the next stage needs. Between them sits text with no timing,
which is kept but never passed off as the transcript the pipeline promised.
"""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from yt_dlp.utils import DownloadCancelled

from backend.services.video_download.web.downloader import DownloadedVideo
from backend.schemas.browser import CaptionCandidate
from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.forced_alignment import AlignedWord, ForcedAlignmentResult
from backend.services.video_download.web.pipeline import process_downloaded_video
from backend.services.transcription.elevenlabs import TranscriptWord
from backend.services.transcripts import normalize_words
from backend.services.video_download.web.transcript import TranscriptArtifact


@pytest.fixture(autouse=True)
def no_firecrawl_lookup():
    """Keep the Firecrawl page-transcript lookup out of these tests.

    Every case here drives the precedence chain past the supplied captions, so without
    this the real Firecrawl endpoint is called with the project's live API key. That
    costs quota on every run and makes the outcome depend on what the service happens to
    return for the placeholder URL, which is what the transcript source is patched to
    decide.
    """
    with patch(
        "backend.services.video_download.web.pipeline.scrape_public_page_transcript",
        return_value=None,
    ):
        yield


def _request() -> CreateVideoJobRequest:
    return CreateVideoJobRequest(page_url="https://example.com/watch")


def _video(tmp_path: Path) -> DownloadedVideo:
    path = tmp_path / "lecture.mp4"
    path.write_bytes(b"video")
    return DownloadedVideo(title="Lecture", video_path=path)


def test_transcription_failure_keeps_the_video_and_reports_the_error(tmp_path: Path) -> None:
    with patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        side_effect=RuntimeError("hosted API is down"),
    ):
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request(),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )
    assert result.video_path == tmp_path / "lecture.mp4"
    assert result.transcript_error == "RuntimeError"
    assert result.transcript_text_path is None


def test_persist_failure_after_transcription_still_keeps_the_video(tmp_path: Path) -> None:
    """A failure between transcribing and writing must not be reported as a lost video."""
    with patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        return_value=TranscriptArtifact(source="elevenlabs", text="hello"),
    ), patch(
        "backend.services.video_download.web.pipeline.persist_transcript",
        side_effect=OSError("path too long"),
    ):
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request(),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )
    assert result.video_path == tmp_path / "lecture.mp4"
    assert result.transcript_error == "OSError"


def test_cancelling_during_transcription_writes_no_transcript(tmp_path: Path) -> None:
    cancel_event = threading.Event()

    def transcribe_then_cancel(_: Path) -> TranscriptArtifact:
        cancel_event.set()
        return TranscriptArtifact(source="elevenlabs", text="hello")

    with patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        side_effect=transcribe_then_cancel,
    ), patch("backend.services.video_download.web.pipeline.persist_transcript") as persist:
        with pytest.raises(DownloadCancelled):
            process_downloaded_video(
                video=_video(tmp_path),
                request=_request(),
                cancel_event=cancel_event,
                progress_callback=lambda *_: None,
            )
    persist.assert_not_called()


def _timed_artifact() -> TranscriptArtifact:
    words = [
        TranscriptWord(
            text=word, start_seconds=index, end_seconds=index + 1, speaker_id="s0", logprob=-0.1
        )
        for index, word in enumerate(["hello", "there"])
    ]
    return TranscriptArtifact(
        source="elevenlabs",
        text="hello there",
        normalized=normalize_words(words, source="elevenlabs"),
    )


def test_a_page_transcript_no_longer_outranks_timed_transcription(tmp_path: Path) -> None:
    """Untimed text cannot meet the contract, so it is not raced against transcription."""
    with patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        return_value=_timed_artifact(),
    ), patch(
        "backend.services.video_download.web.pipeline.scrape_public_page_transcript",
        return_value="a published transcript with no timing whatsoever",
    ) as scrape:
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request(),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )

    scrape.assert_not_called()
    assert result.transcript_source == "elevenlabs"
    assert result.transcript_error is None
    assert result.transcript_text_path.read_text(encoding="utf-8") == "[00:00-00:02] hello there"


def test_text_with_no_timing_is_saved_but_not_reported_as_a_finished_transcript(
    tmp_path: Path,
) -> None:
    page_text = "a published transcript with no timing whatsoever"
    with patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        side_effect=RuntimeError("hosted API is down"),
    ), patch(
        "backend.services.video_download.web.pipeline.scrape_public_page_transcript",
        return_value=page_text,
    ):
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request(),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )

    assert result.transcript_source == "page_transcript"
    assert result.transcript_error == "untimed_transcript"
    assert result.transcript_text_path.read_text(encoding="utf-8") == page_text


def _request_with_visible_transcript(text: str) -> CreateVideoJobRequest:
    return CreateVideoJobRequest(
        page_url="https://example.com/watch",
        caption_candidates=[
            CaptionCandidate(text=text, format="text", is_visible_transcript=True)
        ],
    )


ENGLISH_PAGE_TRANSCRIPT = (
    "This is an ordinary English transcript with no timing of its own, published on the "
    "page rather than measured against the video."
)
HEBREW_PAGE_TRANSCRIPT = (
    "זהו תמליל בעברית שפורסם בעמוד עצמו וללא כל תזמון מדוד מול הווידאו, ארוך דיו למעבר הסינון."
)


def _forced_alignment_result(text: str) -> ForcedAlignmentResult:
    return ForcedAlignmentResult(
        media_path="video.mp4",
        text=text,
        loss=0.1,
        words=[
            AlignedWord(text=word, start_seconds=index, end_seconds=index + 1, loss=0.05)
            for index, word in enumerate(text.split())
        ],
    )


def test_supplied_untimed_english_text_is_aligned_instead_of_retranscribed(
    tmp_path: Path,
) -> None:
    """Forced alignment is tried before a full retranscription, and wins when it succeeds."""
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media",
        return_value=_forced_alignment_result(ENGLISH_PAGE_TRANSCRIPT),
    ), patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs"
    ) as transcribe:
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request_with_visible_transcript(ENGLISH_PAGE_TRANSCRIPT),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )

    transcribe.assert_not_called()
    assert result.transcript_source == "forced_alignment"
    assert result.transcript_error is None


def test_supplied_untimed_non_english_text_still_falls_back_to_transcription(
    tmp_path: Path,
) -> None:
    """Forced alignment cannot align non-English text, so full transcription still runs."""
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media"
    ) as align, patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        return_value=_timed_artifact(),
    ):
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request_with_visible_transcript(HEBREW_PAGE_TRANSCRIPT),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )

    align.assert_not_called()
    assert result.transcript_source == "elevenlabs"


def test_a_failed_forced_alignment_still_falls_back_to_transcription(tmp_path: Path) -> None:
    with patch(
        "backend.services.video_download.web.transcript.align_text_to_media",
        side_effect=RuntimeError("hosted API is down"),
    ), patch(
        "backend.services.video_download.web.pipeline.transcribe_with_elevenlabs",
        return_value=_timed_artifact(),
    ):
        result = process_downloaded_video(
            video=_video(tmp_path),
            request=_request_with_visible_transcript(ENGLISH_PAGE_TRANSCRIPT),
            cancel_event=threading.Event(),
            progress_callback=lambda *_: None,
        )

    assert result.transcript_source == "elevenlabs"
