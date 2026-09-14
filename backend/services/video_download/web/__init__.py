"""Authenticated non-YouTube browser video downloads.

This package no longer exports `create_app`. Serving it from here is what made the whole
backend import FastAPI just to reach the downloader, and removing that export is what lets
`backend.services` stay importable from a script or a CLI. The app is built by
`backend.api.create_app`.
"""

from .downloader import DownloadedVideo, download_video
from .pipeline import PipelineResult, download_and_transcribe, process_downloaded_video

__all__ = [
    "DownloadedVideo",
    "PipelineResult",
    "download_and_transcribe",
    "download_video",
    "process_downloaded_video",
]
