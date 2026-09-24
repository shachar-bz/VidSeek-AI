"""Dependencies injected into every visual sub-agent tool's RunContext, one set per investigation."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.services.video_frames import VideoFrameSource
from backend.services.visual_indexing.ocr import OcrEngine, configured_ocr_engine
from backend.services.visual_search import VideoVisualMap, ready_video_map
from backend.storage.postgres import (
    PostgresChapters,
    PostgresVideoRecords,
    StoredChapterOutline,
)

from ..budget import InvestigationBudget
from ..image_analysis import ImageAnalyzer, OpenAIImageAnalyzer
from ..result import TimeSpan


@dataclass
class VisualDeps:
    """Per-investigation state: which video, where the viewer was, and what has been spent and seen."""

    video_id: str

    # Where the viewer's player was when the question was asked, in seconds; None when the page
    # gave no position.
    current_time_seconds: float | None = None

    # The connection pool every store is built on; None outside a test means the shared pool.
    pool: object | None = None

    budget: InvestigationBudget = field(default_factory=InvestigationBudget)

    # Every span a tool returned during this investigation. The findings check reads it, so a
    # tool records a span exactly when it hands the agent a moment it may cite.
    spans: list[TimeSpan] = field(default_factory=list)

    # Where frames come from and who looks at them. Built on first use rather than here, so a
    # test that never extracts a frame needs neither a blob store nor an API key.
    frame_source: VideoFrameSource | None = None
    image_analyzer: ImageAnalyzer | None = None

    # The OCR engine for frames whose text was never read; None from it means OCR is not set up
    # on this machine.
    ocr_engine: Callable[[], OcrEngine | None] = configured_ocr_engine

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

    def record_span(self, start_seconds: float, end_seconds: float) -> None:
        with self._lock:
            self.spans.append((start_seconds, end_seconds))

    def video_map(self) -> VideoVisualMap | None:
        """The video's segments, for where its scenes are; None while the index cannot be trusted.

        Read once per investigation, like the chapter outline.
        """
        with self._lock:
            if not self._video_map_read:
                self._video_map = ready_video_map(self.video_id, pool=self.pool)
                self._video_map_read = True
            return self._video_map

    def chapter_at(self, time_seconds: float) -> str | None:
        """The title of the chapter this time falls in; the outline is read once per investigation."""
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
