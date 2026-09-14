"""Coordinates download, transcript precedence, and durable local artifacts."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import requests
from yt_dlp.utils import DownloadCancelled

from backend.schemas.video_jobs import CreateVideoJobRequest, JobPhase

from .downloader import DownloadedVideo, download_video
from .transcript import (
    TranscriptArtifact,
    choose_supplied_transcript,
    persist_transcript,
    scrape_public_page_transcript,
    transcript_from_subtitle_files,
    transcribe_with_elevenlabs,
)


@dataclass(frozen=True)
class PipelineResult:
    """Paths and transcript source produced by a completed pipeline."""

    video_path: Path
    transcript_text_path: Path | None
    transcript_json_path: Path | None
    transcript_source: str | None
    transcript_error: str | None = None


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


def _transcribe_downloaded_video(
    *,
    video: DownloadedVideo,
    request: CreateVideoJobRequest,
    cancel_event: threading.Event,
    progress_callback,
) -> PipelineResult:
    """Apply the caption/page/ElevenLabs precedence and write the chosen transcript."""
    progress_callback(JobPhase.TRANSCRIPT_LOOKUP, 0.8, "Looking for existing captions")
    artifact: TranscriptArtifact | None = choose_supplied_transcript(request.caption_candidates)
    if not artifact:
        artifact = transcript_from_subtitle_files(video.subtitle_paths)
    if cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")

    if not artifact:
        try:
            page_text = scrape_public_page_transcript(request.page_url)
            if page_text:
                artifact = TranscriptArtifact(source="page_transcript", text=page_text)
        except (requests.RequestException, ValueError):
            artifact = None

    if cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")
    if not artifact:
        progress_callback(JobPhase.TRANSCRIPTION, 0.85, "Transcribing with ElevenLabs")
        artifact = transcribe_with_elevenlabs(video.video_path)

    # Transcription can run for many minutes, so re-check before writing anything.
    if cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")
    text_path, json_path = persist_transcript(video.video_path, artifact)
    return PipelineResult(
        video_path=video.video_path,
        transcript_text_path=text_path,
        transcript_json_path=json_path,
        transcript_source=artifact.source,
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

