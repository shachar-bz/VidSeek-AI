"""What the extension observed in the active tab, and the session it observed it with.

These models describe the browser side of one capture: the cookies and headers needed to
reproduce a media request, and the media and caption sources discovered in the page. They
are separate from `video_jobs` because they are inputs to a job rather than part of its
lifecycle, and because the downloader consumes them without caring that a job exists.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MediaKind(str, Enum):
    """Kinds of downloadable media understood by the companion."""

    DIRECT = "direct"
    HLS = "hls"
    DASH = "dash"


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
