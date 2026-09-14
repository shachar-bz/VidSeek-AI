"""Coordinates download, transcript precedence, and durable local artifacts."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import requests
from yt_dlp.utils import DownloadCancelled

from backend.schemas.video_jobs import CreateVideoJobRequest, JobPhase
from backend.services.transcripts import NormalizedTranscript

from .downloader import DownloadedVideo, download_video
from .transcript import (
    TranscriptArtifact,
    align_supplied_transcript,
    choose_supplied_transcript,
    persist_transcript,
    scrape_public_page_transcript,
    transcript_from_subtitle_files,
    transcribe_with_elevenlabs,
)


# Reported when a video came out of the pipeline with text but no timing, which is the one
# way a job can finish with a transcript the next stage still cannot use.
UNTIMED_TRANSCRIPT_ERROR = "untimed_transcript"


@dataclass(frozen=True)
class PipelineResult:
    """Paths and transcript source produced by a completed pipeline.

    `comments_path` is only ever set by the YouTube pipeline; the web route has no source
    of comments and leaves it None. Both routes return this one shape so that the job
    manager keeps a single completion path.
    """

    video_path: Path
    transcript_text_path: Path | None
    transcript_json_path: Path | None
    transcript_source: str | None
    transcript_error: str | None = None
    comments_path: Path | None = None

    # The transcript itself, carried rather than re-read from the `.json` beside the
    # video, so that whatever records the job in Supabase writes the same segments the
    # pipeline produced instead of a round trip through disk. None whenever the pipeline
    # produced no timed transcript, which is exactly when `transcript_error` is set.
    normalized_transcript: NormalizedTranscript | None = None


def process_downloaded_video(
    *,
    video: DownloadedVideo,
    request: CreateVideoJobRequest,
    cancel_event: threading.Event,
    progress_callback,
) -> PipelineResult:
    """Choose the best transcript, falling back without losing the video.

    The video is already on disk by the time this runs, so every transcript failure is
    reported as a transcript error on a successful result rather than raised. Only a
    cancellation propagates, because that must not leave half-written artifacts behind.
    """
    try:
        return _transcribe_downloaded_video(
            video=video,
            request=request,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
    except DownloadCancelled:
        raise
    except Exception as error:
        return PipelineResult(
            video_path=video.video_path,
            transcript_text_path=None,
            transcript_json_path=None,
            transcript_source=None,
            transcript_error=type(error).__name__,
        )


def _raise_if_cancelled(cancel_event: threading.Event) -> None:
    """Abort between stages; each one runs to completion once started."""
    if cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")


def _untimed_text(page_url: str, parked: TranscriptArtifact | None) -> TranscriptArtifact | None:
    """The best untimed text still available, for when no timing could be produced.

    A transcript published on the page is text somebody wrote out, with nothing saying
    when any of it was said. It cannot meet the pipeline's contract, so it is no longer
    raced against the captions: it is what is left to save when the captions were untimed
    and transcription came back with nothing, and it costs a Firecrawl call only then
    rather than on every uncaptioned video.
    """
    if parked is not None:
        return parked
    try:
        page_text = scrape_public_page_transcript(page_url)
    except (requests.RequestException, ValueError):
        return None
    return TranscriptArtifact(source="page_transcript", text=page_text) if page_text else None


def _transcribe_downloaded_video(
    *,
    video: DownloadedVideo,
    request: CreateVideoJobRequest,
    cancel_event: threading.Event,
    progress_callback,
) -> PipelineResult:
    """Produce a timed transcript, and settle for untimed text only when there is none.

    Captions that the page or the download already supplied come first: they are free and
    already timed. Text that was supplied but never timed is not thrown away either: it is
    handed to forced alignment, which fits those same words onto the video's audio rather
    than transcribing it from scratch. Only once both come up empty does anything go to
    ElevenLabs to be transcribed outright — the next stage needs a timestamp on every
    segment, and a transcript without one is a transcript it cannot take. When nothing
    produces timing, the text is still written and the job is reported as untimed rather
    than as complete, so that nothing downstream mistakes it for a transcript it can index.
    """
    progress_callback(JobPhase.TRANSCRIPT_LOOKUP, 0.8, "Looking for existing captions")
    supplied = choose_supplied_transcript(
        request.caption_candidates
    ) or transcript_from_subtitle_files(video.subtitle_paths)
    _raise_if_cancelled(cancel_event)

    artifact = supplied if supplied and supplied.is_timed else None
    if artifact is None and supplied is not None:
        progress_callback(JobPhase.TRANSCRIPTION, 0.82, "Timing the existing transcript")
        artifact = align_supplied_transcript(video.video_path, supplied)

    if artifact is None:
        progress_callback(JobPhase.TRANSCRIPTION, 0.85, "Transcribing with ElevenLabs")
        transcription_failure: Exception | None = None
        try:
            artifact = transcribe_with_elevenlabs(video.video_path)
        except DownloadCancelled:
            raise
        except Exception as error:
            artifact, transcription_failure = None, error

        if artifact is None or not artifact.is_timed:
            # Transcription either failed or measured nothing. Whatever untimed text is
            # left is still worth writing, and is looked for exactly once.
            artifact = _untimed_text(request.page_url, supplied) or artifact
        if artifact is None:
            # Nothing was transcribed and there is no text to fall back on, so the
            # transcription failure is the whole story and belongs to the caller.
            raise transcription_failure

    # Transcription can run for many minutes, so re-check before writing anything.
    _raise_if_cancelled(cancel_event)
    text_path, json_path = persist_transcript(video.video_path, artifact)
    return PipelineResult(
        video_path=video.video_path,
        transcript_text_path=text_path,
        transcript_json_path=json_path,
        transcript_source=artifact.source,
        transcript_error=None if artifact.is_timed else UNTIMED_TRANSCRIPT_ERROR,
        normalized_transcript=artifact.normalized,
    )


def download_and_transcribe(
    *,
    request: CreateVideoJobRequest,
    download_root: Path,
    cancel_event: threading.Event,
    progress_callback,
) -> PipelineResult:
    """Download an authenticated VOD and produce the best available transcript."""
    progress_callback(JobPhase.DOWNLOAD, 0.05, "Downloading video")
    downloaded = download_video(
        page_url=request.page_url,
        page_title=request.page_title,
        candidates=request.media_candidates,
        context=request.browser_context,
        preferred_language=request.preferred_language,
        download_root=download_root,
        cancel_event=cancel_event,
        progress_callback=lambda value: progress_callback(
            JobPhase.DOWNLOAD, 0.05 + value * 0.7, "Downloading video"
        ),
    )
    return process_downloaded_video(
        video=downloaded,
        request=request,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )

