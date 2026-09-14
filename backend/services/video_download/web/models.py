"""Validated API models for authenticated browser video download jobs."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MediaKind(str, Enum):
    """Kinds of downloadable media understood by the companion."""

    DIRECT = "direct"
    HLS = "hls"
    DASH = "dash"


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


class BrowserCookie(BaseModel):
    """One browser cookie scoped to an identified page or media origin."""

    name: str = Field(min_length=1, max_length=512)
    value: str = Field(max_length=16_384)
    domain: str = Field(min_length=1, max_length=512)
    path: str = Field(default="/", min_length=1, max_length=2048)
    secure: bool = False
    http_only: bool = False
    expiration_date: float | None = None


class BrowserContext(BaseModel):
    """Short-lived request context copied from the active Chrome session."""

    cookies: list[BrowserCookie] = Field(default_factory=list, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    user_agent: str = Field(default="", max_length=2048)


class MediaCandidate(BaseModel):
    """A direct file or adaptive-stream URL discovered in the active tab."""

    kind: MediaKind
    url: str = Field(min_length=1, max_length=16_384)
    mime_type: str = Field(default="", max_length=512)
    source: str = Field(default="dom", max_length=64)
    headers: dict[str, str] = Field(default_factory=dict)


class CaptionCandidate(BaseModel):
    """A caption track or visible transcript discovered in the active page."""

    url: str | None = Field(default=None, max_length=16_384)
    text: str | None = Field(default=None, max_length=2_000_000)
    format: str = Field(default="vtt", max_length=32)
    language: str | None = Field(default=None, max_length=64)
    is_active: bool = False
    is_manual: bool = True
    is_visible_transcript: bool = False


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

