"""The video page's contract: one video's metadata, playback link, transcript, outline,
generated insights and pinned answers.

Five reads rather than one, because they have five different costs and five different
lifetimes. The metadata is small and needed immediately; the playback URL is a credential
that expires and has to be re-fetched while the page is still open; the transcript is the
largest thing on the page; the outline is small but exists only once the video is
understood; and the pins change whenever the user pins something. Serving them together
would make the slowest of them the cost of opening the page.

None of these names collide with `backend/video_agent/tools/get_video_outline/result.py`,
which models the same chapters for the *agent*. The two are kept apart on purpose: one is
what a browser renders and the other is what a model reads, and letting a change to either
drag the other along is exactly the coupling that would make the tools hard to change.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .readiness import ReadinessStage

# What a playback link is minted for. The page refreshes it before this elapses rather than
# letting a long video stop playing mid-sentence, so the value is returned to the client
# rather than assumed by it.
PLAYBACK_URL_LIFETIME_SECONDS = 3600

# How long before expiry the page should ask for a new playback URL. Comfortably longer
# than a slow request and far shorter than the lifetime, so a refresh never races the
# expiry it is avoiding.
PLAYBACK_URL_REFRESH_MARGIN_SECONDS = 300


class VisualStatus(str, Enum):
    """How far a video's visual index is. Matches `videos_visual_status_known` in
    `migrations/0022_video_visual_index.sql`.

    Separate from the readiness stage on purpose: the index is built in the background after
    the transcript stages, a video is `ready` to chat about long before its index is, and a
    video whose index failed or was skipped still answers everything its transcript can.
    """

    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class VideoInsights(BaseModel):
    """What the pipeline generated about a video once processing finished.

    Static content, produced once and stored: the page reads it, and nothing here is an
    agent answer or is computed on load. Shared by every account that links the video.
    """

    summary: str
    takeaways: list[str] = Field(default_factory=list)
    # Starter questions derived from the video's chapters. Each opens a new conversation
    # pre-filled with it, so each is stored and sent as exactly the text that message
    # would carry.
    suggested_questions: list[str] = Field(default_factory=list)


class VideoDetail(BaseModel):
    """Everything the video page needs before it fetches anything large.

    `title` is the effective title -- this user's rename when they set one, the captured
    title otherwise -- and `original_title` is what the video itself is called, so the page
    can offer "reset to original" without a second request.

    `insights` is null for any video that has not reached `ready`, which is not an error:
    §1.3 gives the player and the transcript to `understanding`, and the summary, takeaways
    and questions only arrive with `ready`.
    """

    video_id: str
    title: str
    custom_title: str | None = None
    original_title: str

    source_site: str
    source_url: str
    duration_seconds: float | None = None

    tags: list[str] = Field(default_factory=list)
    added_at: str

    stage: ReadinessStage

    transcript_source: str | None = None
    transcript_language: str | None = None
    # "word" or "caption", the `TimingFidelity` value on the video row. Null when there is
    # no transcript. This is what tells the page how much a click-to-seek is worth --
    # `Risk 3` of the specification -- and it is carried for that reason rather than
    # displayed for its own sake.
    transcript_timing_fidelity: str | None = None

    insights: VideoInsights | None = None
    conversation_count: int = 0

    # Whether questions about what the video shows can search the whole video yet. Null only
    # when the row carries no status to report.
    visual_status: VisualStatus | None = None


class PlaybackUrl(BaseModel):
    """A short-lived signed link to the video's bytes, and when it stops working.

    The bytes live in a private container, so this is the only way the page plays anything.
    The URL carries a signature: it is a credential for one blob for one hour and must not
    be logged, stored or put in a link the user can copy.
    """

    url: str
    expires_at: str
    expires_in_seconds: int


class TranscriptLine(BaseModel):
    """One line of the transcript, exactly as `transcript_segments` holds it."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str


class VideoTranscript(BaseModel):
    """A video's whole transcript, in order.

    Unpaged. A transcript is read as a column the user scrolls and the playhead tracks, so
    a page boundary in the middle of it would have to be stitched back together by the
    client before it could highlight anything.

    `timing_fidelity` repeats what `VideoDetail` carries, so that a client which fetched
    only the transcript still knows whether the timings in it can be clicked with confidence.
    """

    video_id: str
    timing_fidelity: str | None = None
    lines: list[TranscriptLine] = Field(default_factory=list)


class ChapterOutlineEntry(BaseModel):
    """One chapter, named, placed and timed, with nothing of what was said in it."""

    chapter_id: str
    chapter_index: int
    title: str
    summary: str
    start_seconds: float
    end_seconds: float


class VideoOutlineResponse(BaseModel):
    """Every chapter of a video, earliest first.

    Empty for a video that has not been divided into chapters, which is every video before
    `ready`. Empty is not an error and the page shows the stage instead.
    """

    video_id: str
    chapters: list[ChapterOutlineEntry] = Field(default_factory=list)


class PinnedAnswer(BaseModel):
    """One answer this user kept, and the way back to where it was said."""

    pin_id: str
    message_id: str
    conversation_id: str
    content: str
    pinned_at: str


class PinnedAnswerList(BaseModel):
    """Every answer this user pinned about this video, most recently pinned first."""

    video_id: str
    pins: list[PinnedAnswer] = Field(default_factory=list)


class PinAnswerRequest(BaseModel):
    """Which assistant message to pin.

    The video is already in the path and the conversation follows from the message, so this
    carries neither: repeating them would be two more values a caller could get wrong and
    the server would have to check agree.
    """

    message_id: str
