"""Public interface for authenticated non-YouTube browser video downloads."""

from .api import create_app
from .downloader import DownloadedVideo, UnsupportedMediaError, download_video
from .models import (
    BrowserContext,
    BrowserCookie,
    CaptionCandidate,
    CreateVideoJobRequest,
    JobPhase,
    JobStatus,
    MediaCandidate,
    MediaKind,
    VideoJobResponse,
)

__all__ = [
    "BrowserContext",
    "BrowserCookie",
    "CaptionCandidate",
    "CreateVideoJobRequest",
    "DownloadedVideo",
    "JobPhase",
    "JobStatus",
    "MediaCandidate",
    "MediaKind",
    "UnsupportedMediaError",
    "VideoJobResponse",
    "create_app",
    "download_video",
]

