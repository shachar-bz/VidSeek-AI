"""Downloads a YouTube video together with its transcript and top comments.

The transcript prefers YouTube's own captions — free, immediate, and already there for
most videos — and only reaches for ElevenLabs' Scribe when a video has none in any
requested language. Comments are independent of both: they come from the Data API
regardless of which transcript path was taken.
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from yt_dlp.utils import DownloadCancelled

from backend.services.transcription.elevenlabs import transcribe_video
from backend.services.transcripts import TimingFidelity, normalize_caption_cues, normalize_words

from .captions import fetch_captions
from .comments import CommentEntry, fetch_top_comments
from .downloader import download_video
from .transcript import CAPTIONS_SOURCE, ELEVENLABS_SOURCE, YouTubeTranscript

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "downloads"
DEFAULT_CAPTION_LANGUAGES = ("en",)
DEFAULT_COMMENT_LIMIT = 100

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YouTubeDownloadResult:
    """Everything fetched locally from one YouTube URL."""

    url: str
    video_id: str
    title: str
    video_path: str
    transcript: YouTubeTranscript
    transcript_path: str
    comments: list[CommentEntry]
    comments_path: str | None


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    """Abort between stages, which is the only place this pipeline can be interrupted."""
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled("Job cancelled")


def _write_comments(video_id: str, output_dir: Path, limit: int) -> tuple[list[CommentEntry], str | None]:
    """Fetch and store the top comments, or give up on them without losing the video.

    Comments need their own API key and their own quota, and a video whose download and
    transcript both succeeded should not be reported as a failure because that key is
    missing or the quota is spent.
    """
    try:
        comments = fetch_top_comments(video_id, limit=limit)
    except (RuntimeError, OSError) as error:
        logger.warning("Could not fetch comments for %s: %s", video_id, error)
        return [], None

    comments_path = output_dir / f"{video_id}.comments.json"
    comments_path.write_text(
        json.dumps([asdict(comment) for comment in comments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return comments, str(comments_path)


def _build_transcript(video_path: str, url: str, output_dir: Path, languages: tuple[str, ...]) -> YouTubeTranscript:
    """Read the captions or transcribe, and normalize whichever timing came back.

    The two sources measure timing at different granularities — caption cues one side,
    individual words the other — and normalizing here is what makes that difference stop
    at this function. Captions that come back with no usable timing are treated the same
    as no captions at all, so a track that measured nothing never displaces the timed
    transcript ElevenLabs would otherwise have produced.
    """
    fetched = fetch_captions(url, output_dir, languages=languages)
    if fetched is not None:
        normalize_fn = (
            normalize_words if fetched.timing_fidelity == TimingFidelity.WORD else normalize_caption_cues
        )
        normalized = normalize_fn(fetched.segments, source=CAPTIONS_SOURCE)
        if normalized is not None:
            return YouTubeTranscript(
                source=CAPTIONS_SOURCE,
                text=" ".join(segment.text for segment in fetched.segments),
                segments=fetched.segments,
                normalized=normalized,
            )

    logger.info("No timed YouTube captions available for %s; transcribing with ElevenLabs", url)
    result = transcribe_video(video_path)
    return YouTubeTranscript(
        source=ELEVENLABS_SOURCE,
        text=result.speech_text,
        elevenlabs_result=result,
        normalized=normalize_words(
            result.words, source=ELEVENLABS_SOURCE, language=result.language_code
        ),
    )


def download_youtube_video(
    url: str,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    caption_languages: tuple[str, ...] = DEFAULT_CAPTION_LANGUAGES,
    comment_limit: int = DEFAULT_COMMENT_LIMIT,
    progress_hook=None,
    cancel_event: threading.Event | None = None,
    supplied_transcript: YouTubeTranscript | None = None,
) -> YouTubeDownloadResult:
    """Download `url`'s video, transcript and top comments into `output_dir`.

    Every artifact is named after the video's own id, so re-running this on the same URL
    overwrites rather than duplicates: `{id}.mp4`, `{id}.transcript.txt`,
    `{id}.comments.json`, and — only when captions exist — the raw `{id}.{lang}.vtt`.

    `progress_hook` and `cancel_event` exist for the companion service, which has to be
    able to report progress and honor a cancel request. Both default to None, so a CLI or
    script call is unaffected. Cancellation is checked between stages and inside the
    download itself; the caption probe, the transcription and the comments call each run
    to completion once started, which is the same granularity the web pipeline offers.
    """
    output_dir = Path(output_dir)
    _raise_if_cancelled(cancel_event)

    hooks = []
    if progress_hook is not None or cancel_event is not None:

        def hook(update: dict) -> None:
            _raise_if_cancelled(cancel_event)
            if progress_hook is not None:
                progress_hook(update)

        hooks.append(hook)

    video = download_video(url, output_dir, progress_hooks=hooks or None)
    _raise_if_cancelled(cancel_event)

    transcript = supplied_transcript if supplied_transcript and supplied_transcript.is_timed else _build_transcript(video.video_path, url, output_dir, caption_languages)
    _raise_if_cancelled(cancel_event)

    transcript_path = output_dir / f"{video.video_id}.transcript.txt"
    transcript_path.write_text(transcript.timestamped_text, encoding="utf-8")

    comments, comments_path = _write_comments(video.video_id, output_dir, comment_limit)

    return YouTubeDownloadResult(
        url=url,
        video_id=video.video_id,
        title=video.title,
        video_path=video.video_path,
        transcript=transcript,
        transcript_path=str(transcript_path),
        comments=comments,
        comments_path=comments_path,
    )
