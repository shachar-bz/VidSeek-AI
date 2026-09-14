"""The job lifecycle the extension polls: what it asks for, and what it gets back.

`VideoJobResponse` is deliberately secret-free — no cookies, no headers, no URLs carrying
signed query parameters — because the extension displays it and the companion has no way
to know what a page put in a token.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .browser import BrowserContext, CaptionCandidate, MediaCandidate


class JobStatus(str, Enum):
    """Externally visible lifecycle states for one video job."""

    AWAITING_BROWSER_DOWNLOAD = "awaiting_browser_download"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPhase(str, Enum):
    """Fine-grained progress phases displayed by the extension."""

    DOWNLOAD = "download"
    TRANSCRIPT_LOOKUP = "transcript_lookup"
    TRANSCRIPTION = "transcription"
    COMPLETE = "complete"


class CreateVideoJobRequest(BaseModel):
    """Everything needed to acquire and transcribe one open-tab video."""

    page_url: str = Field(min_length=1, max_length=16_384)
    page_title: str = Field(default="video", max_length=512)
    preferred_language: str | None = Field(default=None, max_length=64)
    drm_detected: bool = False
    media_candidates: list[MediaCandidate] = Field(default_factory=list, max_length=100)
    caption_candidates: list[CaptionCandidate] = Field(default_factory=list, max_length=50)
    browser_context: BrowserContext = Field(default_factory=BrowserContext)


class BrowserDownloadCompleteRequest(BaseModel):
    """The path Chrome produced after a direct-file download completes."""

    local_path: str = Field(min_length=1, max_length=32_768)


class CaptureRetryRequest(BaseModel):
    """Fresh media request details obtained by an opt-in debugger capture."""

    media_candidates: list[MediaCandidate] = Field(min_length=1, max_length=100)
    browser_context: BrowserContext = Field(default_factory=BrowserContext)


class VideoJobResponse(BaseModel):
    """Secret-free progress and result data returned to the extension."""

    job_id: str
    status: JobStatus
    phase: JobPhase
    progress: float = Field(ge=0.0, le=1.0)
    message: str
    acquisition_mode: str
    video_path: str | None = None
    transcript_text_path: str | None = None
    transcript_json_path: str | None = None
    transcript_source: str | None = None
    error_code: str | None = None
    can_capture: bool = False

