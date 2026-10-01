"""Dependencies injected into every conversation tool's RunContext."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from backend.services.video_frames import VideoFrameSource
from backend.services.visual_search import VISUAL_UNAVAILABLE, VideoVisualMap, ready_video_map
from backend.storage.postgres import (
    PostgresChapters,
    PostgresVideoRecords,
    StoredChapterOutline,
)

from ..citations import RetrievedSpans
from ..image_analysis import ImageAnalyzer, OpenAIImageAnalyzer
from ..visual_budget import VisualBudget


@dataclass
class ConversationDeps:
    """Per-run state the application supplies when a conversation/agent run starts."""

    video_id: str
    timestamps_reliable: bool = True

    # Whether the video has stored YouTube comments. Decides whether the agent is offered
    # `get_viewer_comments` at all, so it is read once per run rather than on every step.
    has_comments: bool = False

    # Whether the video's picture can be searched and looked at: `ready`, `processing` or
    # `unavailable` (`services/visual_search.visual_availability`). Only a ready video is offered
    # the visual tools, and the prompt says which of the other two to tell the user, so it is
    # read once per run like `has_comments`.
    visual_availability: str = VISUAL_UNAVAILABLE

    # Where the viewer's player was when the question was sent, in seconds; None when the
    # page gave no position. What a deictic question ("what is this?") points at.
    current_time_seconds: float | None = None

    # Whether the player was paused at that position: paused, it is the very frame the viewer
    # is looking at; playing, what they asked about may be a few seconds earlier. None when the
    # page did not say.
    player_paused: bool | None = None

    # Shared, and deliberately mutable: the runner fills it as the agent retrieves, and the
    # citation filter reads it to decide which of the answer's citations to keep. The
    # conversation API seeds it with the spans earlier turns retrieved and reads it back to store
    # this turn's. All three need the same per-run record, and deps is the one thing all three
    # already hold.
    retrieved: RetrievedSpans = field(default_factory=RetrievedSpans)

    # The connection pool every tool's store is built on, rather than a store per tool: a
    # store holds nothing but its pool, so injecting one per table would be injecting the
    # same thing several times over and would grow this class with every tool added. Left
    # as None outside a test, which is each store's own way of saying "the shared pool".
    pool: object | None = None

    # What this answer has spent on the visual tools. One run is one answer, so a fresh
    # budget per run is a fresh budget per turn.
    visual_budget: VisualBudget = field(default_factory=VisualBudget)

    # Where frames come from and who looks at them. Built on first use rather than here, so
    # a run that never looks at the picture needs neither a blob store nor an image model.
    frame_source: VideoFrameSource | None = None
    image_analyzer: ImageAnalyzer | None = None

    _chapters: tuple[StoredChapterOutline, ...] | None = field(default=None, repr=False)
    _video_map: VideoVisualMap | None = field(default=None, repr=False)
    _video_map_read: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def frames(self) -> VideoFrameSource:
        with self._lock:
            if self.frame_source is None:
                self.frame_source = VideoFrameSource(video_records=PostgresVideoRecords(self.pool))
            return self.frame_source

    def analyzer(self) -> ImageAnalyzer:
        with self._lock:
            if self.image_analyzer is None:
                self.image_analyzer = OpenAIImageAnalyzer()
            return self.image_analyzer

    def video_map(self) -> VideoVisualMap | None:
        """The video's segments, for where its shots and scenes are; None while the index cannot be trusted.

        Read once per run, like the chapter outline.
        """
        with self._lock:
            if not self._video_map_read:
                self._video_map = ready_video_map(self.video_id, pool=self.pool)
                self._video_map_read = True
            return self._video_map

    def chapter_at(self, time_seconds: float) -> str | None:
        """The title of the chapter this time falls in; the outline is read once per run."""
        with self._lock:
            if self._chapters is None:
                self._chapters = tuple(PostgresChapters(self.pool).video_outline(self.video_id))
            chapters = self._chapters
        current = None
        for chapter in chapters:
            if chapter.start_seconds > time_seconds:
                break
            current = chapter
        return current.title if current is not None else None
