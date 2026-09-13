"""Public interface of the YouTube download module."""

from .captions import fetch_captions
from .comments import CommentEntry, fetch_top_comments
from .downloader import DownloadedVideo, download_video
from .pipeline import (
    DEFAULT_CAPTION_LANGUAGES,
    DEFAULT_COMMENT_LIMIT,
    DEFAULT_OUTPUT_DIR,
    YouTubeDownloadResult,
    download_youtube_video,
)
from .transcript import CaptionSegment, YouTubeTranscript

__all__ = [
    "CaptionSegment",
    "CommentEntry",
    "DEFAULT_CAPTION_LANGUAGES",
    "DEFAULT_COMMENT_LIMIT",
    "DEFAULT_OUTPUT_DIR",
    "DownloadedVideo",
    "YouTubeDownloadResult",
    "YouTubeTranscript",
    "download_video",
    "download_youtube_video",
    "fetch_captions",
    "fetch_top_comments",
]
