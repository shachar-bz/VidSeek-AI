"""Stand-ins for what the video agent's look tools reach: the frame source and the image model.

Shared by the look tools' test modules, since each needs the same two: a frame source that
hands back small real JPEGs (so a grid is really built) or fails the way extraction fails, and
an image analyzer that records what it was sent and answers with numbered cells. Every store
behind them reads from `FakePool`.
"""

from __future__ import annotations

import io

from PIL import Image

from backend.services.video_frames import JPEG, ExtractedFrame
from backend.video_agent.image_analysis import CandidateAnalysis, CandidateVerdict, FrameAnalysis
from backend.video_agent.tools.deps import ConversationDeps

VIDEO_ID = "11111111-2222-3333-4444-555555555555"


def small_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 50, 50)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeRunContext:
    """The single attribute the tools read off a RunContext."""

    def __init__(self, deps: ConversationDeps):
        self.deps = deps


class FakeFrameSource:
    """Hands back a small JPEG per time asked for, or fails the way extraction fails."""

    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.calls: list[dict] = []

    def frames(self, video_id, times, *, long_side=512, lossless=False):
        self.calls.append({"video_id": video_id, "times": list(times), "long_side": long_side})
        if self.failure is not None:
            raise self.failure
        return [ExtractedFrame(time_seconds=time, image_bytes=small_jpeg(), media_type=JPEG) for time in times]


class FakeImageAnalyzer:
    """Answers a sequence or a contact sheet with one numbered entry per cell, or fails like a model call.

    `verdicts` sets what each contact-sheet cell is judged, in order; `answered` how many cells
    get an answer at all, for a model that gives too few or too many.
    """

    def __init__(
        self,
        failure: Exception | None = None,
        *,
        verdicts: list[str] | None = None,
        answered: int | None = None,
    ):
        self.failure = failure
        self.verdicts = verdicts
        self.answered = answered
        self.sequence_calls: list[tuple] = []
        self.candidate_calls: list[tuple] = []

    async def analyze_sequence(self, question, grid_jpeg, cells):
        self.sequence_calls.append((question, grid_jpeg, list(cells)))
        if self.failure is not None:
            raise self.failure
        return FrameAnalysis(
            frames=[f"Cell {position}" for position in range(1, self._count(len(cells)) + 1)],
            answer="He picks up the cup.",
        )

    async def analyze_candidates(self, question, grid_jpeg, cell_times):
        self.candidate_calls.append((question, grid_jpeg, list(cell_times)))
        if self.failure is not None:
            raise self.failure
        verdicts = self.verdicts or ["yes"] * len(cell_times)
        return CandidateAnalysis(
            frames=[
                CandidateVerdict(description=f"Cell {position}", present=verdicts[(position - 1) % len(verdicts)])
                for position in range(1, self._count(len(cell_times)) + 1)
            ]
        )

    def _count(self, cells: int) -> int:
        return cells if self.answered is None else self.answered


def look_deps(
    pool,
    *,
    frame_source: FakeFrameSource | None = None,
    analyzer: FakeImageAnalyzer | None = None,
) -> ConversationDeps:
    return ConversationDeps(
        video_id=VIDEO_ID,
        current_time_seconds=25.0,
        pool=pool,
        frame_source=frame_source or FakeFrameSource(),
        image_analyzer=analyzer or FakeImageAnalyzer(),
    )
