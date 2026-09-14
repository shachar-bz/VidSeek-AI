"""Runs the YouTube pipeline as a companion job, in the shape the job manager expects.

The YouTube module predates the companion service and returns its own result type. This
adapter is the whole of the translation: it gives `run_youtube_job` the same signature and
the same `PipelineResult` return as `download_and_transcribe`, so `JobManager` finishes
both routes through one code path rather than branching on which pipeline ran.

The transcript is rewritten through the web pipeline's `persist_transcript`, so a YouTube
job produces the same `.transcript.txt` and `.transcript.json` pair beside the video that
the extension already knows how to display. That `.txt` is the same path the YouTube
module already wrote for a CLI run — the video is `{id}.mp4`, so both resolve to
`{id}.transcript.txt` — and both now write the same normalized transcript, so whichever
runs last leaves the same file behind.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from backend.schemas.video_jobs import CreateVideoJobRequest, JobPhase

from .web.pipeline import UNTIMED_TRANSCRIPT_ERROR, PipelineResult
from .web.transcript import CaptionSegment, TranscriptArtifact, persist_transcript
from .youtube.pipeline import YouTubeDownloadResult, download_youtube_video
from .youtube.transcript import CAPTIONS_SOURCE

# Where the download ends and the transcript begins, as a fraction of the job. The web
# route reports the same split, so the extension's progress bar behaves identically.
DOWNLOAD_PROGRESS_CEILING = 0.75


def _caption_languages(request: CreateVideoJobRequest) -> tuple[str, ...]:
    """Ask YouTube for the viewer's language first, then fall back to English."""
    languages = []
    if request.preferred_language:
        languages.extend([request.preferred_language, request.preferred_language.split("-")[0]])
    languages.append("en")
    return tuple(dict.fromkeys(languages))


def _artifact(result: YouTubeDownloadResult) -> TranscriptArtifact:
    """Turn the YouTube transcript into the artifact `persist_transcript` writes.

    `transcript_source` passes through unchanged, so the extension sees the same
    `youtube_captions` or `elevenlabs` value the YouTube module decided on, and so does
    the normalized transcript: the YouTube pipeline already built it, and rebuilding it
    here would be a second chance to build it differently.
    """
    transcript = result.transcript
    if transcript.source == CAPTIONS_SOURCE:
        return TranscriptArtifact(
            source=transcript.source,
            text=transcript.text,
            segments=[
                CaptionSegment(
                    text=segment.text,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                )
                for segment in transcript.segments
            ],
            normalized=transcript.normalized,
        )

    scribe = transcript.elevenlabs_result
    return TranscriptArtifact(
        source=transcript.source,
        text=transcript.text,
        language=scribe.language_code if scribe else None,
        details=asdict(scribe) if scribe else {},
        normalized=transcript.normalized,
    )


def run_youtube_job(
    *,
    request: CreateVideoJobRequest,
    download_root: Path,
    cancel_event: threading.Event,
    progress_callback,
) -> PipelineResult:
    """Download a YouTube video and its transcript into the companion's download root."""
    progress_callback(JobPhase.DOWNLOAD, 0.05, "Downloading from YouTube")

    def report(update: dict) -> None:
        total = update.get("total_bytes") or update.get("total_bytes_estimate") or 0
        downloaded = update.get("downloaded_bytes") or 0
        if total:
            fraction = min(downloaded / total, 0.99)
            progress_callback(
                JobPhase.DOWNLOAD,
                0.05 + fraction * (DOWNLOAD_PROGRESS_CEILING - 0.05),
                "Downloading from YouTube",
            )

    result = download_youtube_video(
        request.page_url,
        output_dir=download_root,
        caption_languages=_caption_languages(request),
        progress_hook=report,
        cancel_event=cancel_event,
    )

    progress_callback(JobPhase.TRANSCRIPT_LOOKUP, 0.9, "Saving transcript")
    video_path = Path(result.video_path)
    artifact = _artifact(result)
    text_path, json_path = persist_transcript(video_path, artifact)
    return PipelineResult(
        video_path=video_path,
        transcript_text_path=text_path,
        transcript_json_path=json_path,
        transcript_source=result.transcript.source,
        # A YouTube job has nowhere left to look for timing: captions and Scribe are both
        # already behind it. Reporting it as untimed is what stops a transcript the next
        # stage cannot use from being handed on as a finished one.
        transcript_error=None if artifact.is_timed else UNTIMED_TRANSCRIPT_ERROR,
        comments_path=Path(result.comments_path) if result.comments_path else None,
        normalized_transcript=artifact.normalized,
        comments=tuple(result.comments),
    )
