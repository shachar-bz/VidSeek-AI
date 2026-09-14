"""Downloads a YouTube video together with its transcript and top comments.

The transcript prefers YouTube's own captions — free, immediate, and already there for
most videos — and only reaches for ElevenLabs' Scribe when a video has none in any
requested language. Comments are independent of both: they come from the Data API
regardless of which transcript path was taken.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from ..ElevenLabs_transcription import transcribe_video
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
    comments_path: str


def _build_transcript(video_path: str, url: str, output_dir: Path, languages: tuple[str, ...]) -> YouTubeTranscript:
    segments = fetch_captions(url, output_dir, languages=languages)
    if segments is not None:
        return YouTubeTranscript(
            source=CAPTIONS_SOURCE,
            text=" ".join(segment.text for segment in segments),
            segments=segments,
        )

    logger.info("No YouTube captions available for %s; transcribing with ElevenLabs", url)
    result = transcribe_video(video_path)
    return YouTubeTranscript(
        source=ELEVENLABS_SOURCE,
        text=result.speech_text,
        elevenlabs_result=result,
    )


def download_youtube_video(
    url: str,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    caption_languages: tuple[str, ...] = DEFAULT_CAPTION_LANGUAGES,
    comment_limit: int = DEFAULT_COMMENT_LIMIT,
) -> YouTubeDownloadResult:
    """Download `url`'s video, transcript and top comments into `output_dir`.

    Every artifact is named after the video's own id, so re-running this on the same URL
    overwrites rather than duplicates: `{id}.mp4`, `{id}.transcript.txt`,
    `{id}.comments.json`, and — only when captions exist — the raw `{id}.{lang}.vtt`.
    """
    output_dir = Path(output_dir)
    video = download_video(url, output_dir)

    transcript = _build_transcript(video.video_path, url, output_dir, caption_languages)
    transcript_path = output_dir / f"{video.video_id}.transcript.txt"
    transcript_path.write_text(transcript.text, encoding="utf-8")

    comments = fetch_top_comments(video.video_id, limit=comment_limit)
    comments_path = output_dir / f"{video.video_id}.comments.json"
    comments_path.write_text(
        json.dumps([asdict(comment) for comment in comments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return YouTubeDownloadResult(
        url=url,
        video_id=video.video_id,
        title=video.title,
        video_path=video.video_path,
        transcript=transcript,
        transcript_path=str(transcript_path),
        comments=comments,
        comments_path=str(comments_path),
    )
