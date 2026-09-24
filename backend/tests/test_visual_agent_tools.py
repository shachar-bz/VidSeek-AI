"""Tests for the visual sub-agent's three tools, called directly with fakes behind a real VisualDeps.

No frame is extracted, no image model or OCR worker is reached, and no database is opened: the
frame source, the image analyzer and the OCR engine are stand-ins that record what they were
asked, and every store reads from `FakePool`. What is real is the deps object each tool spends
its budget on and records its spans into, since those are what the findings check reads.
"""

import asyncio
import io

import pytest
from PIL import Image

from backend.services.video_frames import (
    JPEG,
    PNG,
    READABLE_LONG_SIDE,
    ExtractedFrame,
    FrameExtractionError,
    VideoNotStoredError,
)
from backend.services.visual_indexing.ocr import FrameReading, OcrError, TextBlock
from backend.storage.postgres import StoredKeyframe
from backend.tests.fake_postgres import FakePool
from backend.visual_agent.budget import MAX_IMAGES, MAX_TOOL_CALLS
from backend.visual_agent.image_analysis import FrameAnalysis
from backend.visual_agent.tools.budget_spent import BudgetSpent
from backend.visual_agent.tools.deps import VisualDeps
from backend.visual_agent.tools.get_transcript_window import (
    MAX_WINDOW_SECONDS,
    TranscriptWindow,
    get_transcript_window,
)
from backend.visual_agent.tools.read_frame_text import (
    FrameTexts,
    covering_keyframe,
    read_frame_text,
)
from backend.visual_agent.tools.view_frames import ViewedFrames, view_frames

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

OUTLINE_ROWS = [
    {
        "chapter_id": "chapter-0",
        "chapter_index": 0,
        "title": "Introduction",
        "summary": "Who the speaker is.",
        "start_seconds": 0.0,
        "end_seconds": 120.0,
    },
    {
        "chapter_id": "chapter-1",
        "chapter_index": 1,
        "title": "Kafka partitions",
        "summary": "How a topic is split.",
        "start_seconds": 120.0,
        "end_seconds": 600.0,
    },
]


def _keyframe_row(
    time_seconds: float,
    text: str | None,
    engine: str | None,
    segment_index: int,
    segment_start: float,
    segment_end: float,
) -> dict:
    return {
        "time_seconds": time_seconds,
        "ocr_text": text,
        "ocr_engine": engine,
        "segment_index": segment_index,
        "segment_start_seconds": segment_start,
        "segment_end_seconds": segment_end,
    }


# Segment 0 runs 0-12 s with two read keyframes; segment 1 runs 12-30 s and its one keyframe
# is not read yet; segment 2 runs 130-140 s, read and blank.
KEYFRAME_ROWS = [
    _keyframe_row(2.0, "Agenda", "surya-ocr-2", 0, 0.0, 12.0),
    _keyframe_row(8.0, "Kafka\nPartitions", "surya-ocr-2", 0, 0.0, 12.0),
    _keyframe_row(14.0, None, None, 1, 12.0, 30.0),
    _keyframe_row(131.0, None, "surya-ocr-2", 2, 130.0, 140.0),
]
KEYFRAMES = [
    StoredKeyframe(
        time_seconds=row["time_seconds"],
        text=row["ocr_text"],
        engine=row["ocr_engine"],
        segment_index=row["segment_index"],
        segment_start_seconds=row["segment_start_seconds"],
        segment_end_seconds=row["segment_end_seconds"],
    )
    for row in KEYFRAME_ROWS
]


def _png(size: tuple[int, int] = (64, 36), mode: str = "RGBA") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeRunContext:
    """The single attribute the tools read off a RunContext."""

    def __init__(self, deps: VisualDeps):
        self.deps = deps


class FakeFrameSource:
    """Hands back a frame per time asked for, or fails the way extraction fails."""

    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.calls: list[dict] = []

    def frames(self, video_id, times, *, long_side=512, lossless=False):
        self.calls.append(
            {"video_id": video_id, "times": list(times), "long_side": long_side, "lossless": lossless}
        )
        if self.failure is not None:
            raise self.failure
        return [
            ExtractedFrame(
                time_seconds=time_seconds,
                image_bytes=_png() if lossless else b"jpeg-bytes",
                media_type=PNG if lossless else JPEG,
            )
            for time_seconds in times
        ]


class FakeImageAnalyzer:
    """Says what each frame shows, or fails the way a model call fails."""

    def __init__(self, observations: int | None = None, failure: Exception | None = None):
        # How many observations to give back; None means one per frame.
        self.observations = observations
        self.failure = failure
        self.calls: list[tuple[str, list[ExtractedFrame]]] = []

    async def analyze(self, question, frames):
        self.calls.append((question, list(frames)))
        if self.failure is not None:
            raise self.failure
        count = len(frames) if self.observations is None else self.observations
        return FrameAnalysis(
            frames=[f"Observation {position}" for position in range(1, count + 1)],
            answer="A whiteboard with a diagram.",
        )


class FakeOcrEngine:
    """Reads the text it is told to for every image, or fails the way the OCR worker fails."""

    name = "fake-ocr"

    def __init__(self, reading: FrameReading | None = None, failure: Exception | None = None):
        self.reading = reading or FrameReading(blocks=(TextBlock("Consumer groups", "Text", 0.95),))
        self.failure = failure
        self.images: list[Image.Image] = []

    def read(self, images):
        self.images.extend(images)
        if self.failure is not None:
            raise self.failure
        return [self.reading for _ in images]


def _deps(
    pool: FakePool | None = None,
    *,
    frame_source: FakeFrameSource | None = None,
    analyzer: FakeImageAnalyzer | None = None,
    engine: FakeOcrEngine | None = None,
) -> VisualDeps:
    return VisualDeps(
        video_id=VIDEO_ID,
        current_time_seconds=130.0,
        pool=pool if pool is not None else FakePool(rows=OUTLINE_ROWS),
        frame_source=frame_source or FakeFrameSource(),
        image_analyzer=analyzer or FakeImageAnalyzer(),
        ocr_engine=lambda: engine,
    )


def _view(deps: VisualDeps, timestamps: list[float], question: str = "What is drawn?"):
    return asyncio.run(view_frames(FakeRunContext(deps), timestamps, question))


def _read_text(deps: VisualDeps, timestamps: list[float]):
    return asyncio.run(read_frame_text(FakeRunContext(deps), timestamps))


def _outline_reads(pool: FakePool) -> int:
    return sum("from public.chapters" in statement for statement in pool.statements)


# --- view_frames ------------------------------------------------------------------------


def test_viewing_frames_returns_what_each_one_showed_and_records_a_moment_per_frame() -> None:
    source, analyzer = FakeFrameSource(), FakeImageAnalyzer()
    deps = _deps(frame_source=source, analyzer=analyzer)

    result = _view(deps, [130.0, 131.5], "What is on the whiteboard?")

    assert isinstance(result, ViewedFrames)
    assert [(frame.time_seconds, frame.timestamp, frame.chapter, frame.observation) for frame in result.frames] == [
        (130.0, "02:10", "Kafka partitions", "Observation 1"),
        (131.5, "02:11", "Kafka partitions", "Observation 2"),
    ]
    assert result.answer == "A whiteboard with a diagram."
    assert result.note is None
    assert deps.spans == [(130.0, 130.0), (131.5, 131.5)]
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 2)
    assert result.budget == "5 tool calls and 6 images left."
    # Small JPEGs of this video, and the question passed on to the image model as asked.
    assert source.calls == [
        {"video_id": VIDEO_ID, "times": [130.0, 131.5], "long_side": 512, "lossless": False}
    ]
    assert analyzer.calls[0][0] == "What is on the whiteboard?"
    assert [frame.time_seconds for frame in analyzer.calls[0][1]] == [130.0, 131.5]


def test_repeated_and_negative_times_are_looked_at_once_from_the_start() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    _view(deps, [-4.0, 0.0, 10.0, 10.0])

    assert source.calls[0]["times"] == [0.0, 10.0]
    assert deps.budget.images_used == 2


def test_more_than_six_times_are_cut_to_the_first_six_and_says_so() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [float(second) for second in range(8)])

    assert source.calls[0]["times"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert len(result.frames) == 6
    assert "Only the first 6 times were looked at." in result.note
    assert deps.budget.images_used == 6


def test_only_the_images_left_are_granted_and_the_note_says_so() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    deps.budget.take_images(MAX_IMAGES - 2)

    result = _view(deps, [10.0, 20.0, 30.0, 40.0])

    assert source.calls[0]["times"] == [10.0, 20.0]
    assert [frame.time_seconds for frame in result.frames] == [10.0, 20.0]
    assert result.note == "Only 2 images were left, so only the first 2 times were looked at."
    assert deps.spans == [(10.0, 10.0), (20.0, 20.0)]


def test_with_no_images_left_nothing_is_extracted() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)
    deps.budget.take_images(MAX_IMAGES)

    result = _view(deps, [10.0])

    assert result.frames == []
    assert result.note == "No images are left to look with."
    assert source.calls == []
    assert deps.spans == []


def test_no_times_is_a_spent_call_that_looks_at_nothing() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    result = _view(deps, [])

    assert result.note == "No times were given."
    assert source.calls == []
    assert deps.budget.tool_calls_used == 1


@pytest.mark.parametrize(
    "failure",
    [FrameExtractionError("The video has no frame at 900.0 s"), VideoNotStoredError("no stored file")],
)
def test_frames_that_cannot_be_extracted_give_their_images_back(failure: Exception) -> None:
    analyzer = FakeImageAnalyzer()
    deps = _deps(frame_source=FakeFrameSource(failure=failure), analyzer=analyzer)

    result = _view(deps, [900.0, 901.0])

    assert result.frames == []
    assert result.note == f"The frames could not be extracted: {failure}"
    assert deps.budget.images_used == 0
    assert deps.budget.tool_calls_used == 1
    assert deps.spans == []
    assert analyzer.calls == []


def test_a_failing_image_model_is_a_note_and_its_images_stay_spent() -> None:
    deps = _deps(analyzer=FakeImageAnalyzer(failure=RuntimeError("provider down")))

    result = _view(deps, [10.0, 20.0])

    assert result.frames == []
    assert result.note == "The image model failed to look at the frames."
    assert deps.budget.images_used == 2
    # Nothing was seen, so nothing may be cited.
    assert deps.spans == []


def test_fewer_observations_than_frames_still_returns_every_frame() -> None:
    deps = _deps(analyzer=FakeImageAnalyzer(observations=1))

    result = _view(deps, [10.0, 20.0])

    assert [frame.observation for frame in result.frames] == [
        "Observation 1",
        "The image model gave no separate observation for this frame.",
    ]
    assert deps.spans == [(10.0, 10.0), (20.0, 20.0)]


def test_extra_observations_are_ignored() -> None:
    deps = _deps(analyzer=FakeImageAnalyzer(observations=3))

    result = _view(deps, [10.0])

    assert [frame.observation for frame in result.frames] == ["Observation 1"]


def test_after_six_calls_view_frames_does_no_work_and_says_the_budget_is_spent() -> None:
    source = FakeFrameSource()
    deps = _deps(frame_source=source)

    results = [_view(deps, [float(call)]) for call in range(MAX_TOOL_CALLS + 1)]

    assert all(isinstance(result, ViewedFrames) for result in results[:-1])
    assert results[-2].budget.startswith("That was your last tool call")
    assert isinstance(results[-1], BudgetSpent)
    assert results[-1].budget_spent is True
    assert len(source.calls) == MAX_TOOL_CALLS


def test_the_chapter_outline_is_read_once_per_investigation() -> None:
    pool = FakePool(rows=OUTLINE_ROWS)
    deps = _deps(pool)

    first = _view(deps, [10.0])
    second = _view(deps, [200.0])

    assert first.frames[0].chapter == "Introduction"
    assert second.frames[0].chapter == "Kafka partitions"
    assert _outline_reads(pool) == 1
    assert pool.recorded[0].parameters == (VIDEO_ID,)


def test_a_video_with_no_chapters_gives_frames_no_chapter() -> None:
    deps = _deps(FakePool())

    assert _view(deps, [10.0]).frames[0].chapter is None


# --- covering_keyframe ------------------------------------------------------------------


def test_a_keyframe_s_text_stretches_to_the_next_keyframe_of_its_segment() -> None:
    assert covering_keyframe(KEYFRAMES, 5.0) == (KEYFRAMES[0], 8.0)
    assert covering_keyframe(KEYFRAMES, 2.0) == (KEYFRAMES[0], 8.0)


def test_the_last_keyframe_of_a_segment_stretches_to_the_segment_s_end() -> None:
    assert covering_keyframe(KEYFRAMES, 8.0) == (KEYFRAMES[1], 12.0)
    assert covering_keyframe(KEYFRAMES, 11.9) == (KEYFRAMES[1], 12.0)
    assert covering_keyframe(KEYFRAMES, 135.0) == (KEYFRAMES[3], 140.0)


def test_a_time_before_the_first_keyframe_is_not_covered() -> None:
    assert covering_keyframe(KEYFRAMES, 1.0) is None


def test_a_time_between_a_segment_s_start_and_its_first_keyframe_is_not_covered() -> None:
    # The stretch ends where the segment does, exclusive, so 12 s belongs to no stretch.
    assert covering_keyframe(KEYFRAMES, 12.0) is None
    assert covering_keyframe(KEYFRAMES, 130.5) is None


def test_a_keyframe_ocr_has_not_read_covers_nothing() -> None:
    assert covering_keyframe(KEYFRAMES, 20.0) is None


def test_a_time_past_every_segment_or_with_no_keyframes_is_not_covered() -> None:
    assert covering_keyframe(KEYFRAMES, 140.0) is None
    assert covering_keyframe([], 5.0) is None


# --- read_frame_text --------------------------------------------------------------------


def test_stored_text_is_returned_with_the_stretch_it_is_shown_for() -> None:
    source, engine = FakeFrameSource(), FakeOcrEngine()
    pool = FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS])
    deps = _deps(pool, frame_source=source, engine=engine)

    result = _read_text(deps, [5.0, 135.0])

    assert isinstance(result, FrameTexts)
    assert [(text.time_seconds, text.text, text.source, text.start_seconds, text.end_seconds) for text in result.texts] == [
        (5.0, "Agenda", "stored", 2.0, 8.0),
        # Read and blank: no text, and still a moment the agent may cite.
        (135.0, None, "stored", 131.0, 140.0),
    ]
    assert [text.chapter for text in result.texts] == ["Introduction", "Kafka partitions"]
    assert deps.spans == [(2.0, 8.0), (131.0, 140.0)]
    # Nothing was extracted or read now, and no image was spent.
    assert source.calls == [] and engine.images == []
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 0)
    assert pool.recorded[0].parameters == (VIDEO_ID,)
    assert "from public.video_keyframes" in pool.statements[0]


def test_an_uncovered_time_is_read_now_from_a_full_size_lossless_frame() -> None:
    source, engine = FakeFrameSource(), FakeOcrEngine()
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), frame_source=source, engine=engine)

    result = _read_text(deps, [20.0])

    assert source.calls == [
        {"video_id": VIDEO_ID, "times": [20.0], "long_side": READABLE_LONG_SIDE, "lossless": True}
    ]
    # The PNG was decoded and handed to the engine as an RGB image.
    assert [(image.mode, image.size) for image in engine.images] == [("RGB", (64, 36))]
    (text,) = result.texts
    assert (text.text, text.source, text.start_seconds, text.end_seconds) == (
        "Consumer groups",
        "read_now",
        20.0,
        20.0,
    )
    assert text.note is None
    assert deps.spans == [(20.0, 20.0)]
    assert deps.budget.images_used == 0


def test_a_frame_read_now_that_shows_no_text_is_still_a_moment_that_was_read() -> None:
    engine = FakeOcrEngine(reading=FrameReading())
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), engine=engine)

    (text,) = _read_text(deps, [1.0]).texts

    assert (text.text, text.source) == (None, "read_now")
    assert deps.spans == [(1.0, 1.0)]


def test_stored_and_read_now_texts_come_back_in_the_order_asked_for() -> None:
    source = FakeFrameSource()
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), frame_source=source, engine=FakeOcrEngine())

    result = _read_text(deps, [20.0, 5.0, 1.0])

    assert [(text.time_seconds, text.source) for text in result.texts] == [
        (20.0, "read_now"),
        (5.0, "stored"),
        (1.0, "read_now"),
    ]
    # Only the uncovered times were extracted, in one batch.
    assert [call["times"] for call in source.calls] == [[20.0, 1.0]]


def test_without_ocr_an_uncovered_time_comes_back_unread_and_uncitable() -> None:
    source = FakeFrameSource()
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), frame_source=source, engine=None)

    result = _read_text(deps, [20.0, 5.0])

    unread, stored = result.texts
    assert (unread.text, unread.source) == (None, "unread")
    assert "OCR is not set up" in unread.note and "view_frames" in unread.note
    assert stored.source == "stored"
    # Only the stored text's stretch is a moment the agent may cite.
    assert deps.spans == [(2.0, 8.0)]
    assert source.calls == []


def test_an_ocr_failure_comes_back_unread_with_the_reason() -> None:
    engine = FakeOcrEngine(failure=OcrError("the Surya worker timed out"))
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), engine=engine)

    (text,) = _read_text(deps, [20.0]).texts

    assert text.source == "unread"
    assert text.note == "OCR failed: the Surya worker timed out"
    assert deps.spans == []


def test_a_frame_the_engine_gave_no_reading_for_comes_back_unread() -> None:
    class ShortEngine(FakeOcrEngine):
        def read(self, images):
            return super().read(images)[:1]

    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), engine=ShortEngine())

    first, second = _read_text(deps, [20.0, 25.0]).texts

    assert (first.source, first.text) == ("read_now", "Consumer groups")
    assert (second.source, second.text) == ("unread", None)
    assert second.note == "OCR returned no reading for this frame."
    assert deps.spans == [(20.0, 20.0)]


def test_a_frame_that_cannot_be_decoded_for_reading_comes_back_unread() -> None:
    class BrokenImageSource(FakeFrameSource):
        def frames(self, video_id, times, *, long_side=512, lossless=False):
            return [
                ExtractedFrame(time_seconds=time_seconds, image_bytes=b"not an image", media_type=PNG)
                for time_seconds in times
            ]

    engine = FakeOcrEngine()
    deps = _deps(
        FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), frame_source=BrokenImageSource(), engine=engine
    )

    (text,) = _read_text(deps, [20.0]).texts

    assert text.source == "unread"
    assert text.note.startswith("The extracted frames could not be decoded")
    assert engine.images == []
    assert deps.spans == []


def test_a_frame_that_cannot_be_extracted_for_reading_comes_back_unread() -> None:
    engine = FakeOcrEngine()
    deps = _deps(
        FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]),
        frame_source=FakeFrameSource(failure=VideoNotStoredError("Video has no stored file")),
        engine=engine,
    )

    (text,) = _read_text(deps, [20.0]).texts

    assert text.source == "unread"
    assert text.note == "The frames could not be extracted: Video has no stored file"
    assert engine.images == []
    assert deps.spans == []


def test_text_longer_than_the_limit_is_cut_and_says_so() -> None:
    engine = FakeOcrEngine(reading=FrameReading(blocks=(TextBlock("x" * 2500, "Text", 0.9),)))
    deps = _deps(FakePool(responses=[[], OUTLINE_ROWS]), engine=engine)

    (text,) = _read_text(deps, [3.0]).texts

    assert text.text == "x" * 2000 + " [cut]"


def test_more_than_six_times_are_cut_to_the_first_six_and_says_so_when_reading() -> None:
    deps = _deps(FakePool(responses=[KEYFRAME_ROWS, OUTLINE_ROWS]), engine=FakeOcrEngine())

    result = _read_text(deps, [float(second) for second in range(1, 9)])

    assert [text.time_seconds for text in result.texts] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert result.note == "Only the first 6 times were read."


def test_after_six_calls_read_frame_text_does_no_work() -> None:
    pool = FakePool(rows=[])
    deps = _deps(pool, engine=None)

    results = [_read_text(deps, [20.0]) for _ in range(MAX_TOOL_CALLS + 1)]

    assert isinstance(results[-1], BudgetSpent)
    assert results[-2].budget.startswith("That was your last tool call")
    keyframe_reads = sum("from public.video_keyframes" in statement for statement in pool.statements)
    assert keyframe_reads == MAX_TOOL_CALLS


# --- get_transcript_window --------------------------------------------------------------


SEGMENT_ROWS = [
    {"segment_index": 40, "start_seconds": 128.0, "end_seconds": 133.5, "text": "Here is the diagram."},
    {"segment_index": 41, "start_seconds": 133.5, "end_seconds": 140.0, "text": "Each box is a partition."},
]


def _transcript(deps: VisualDeps, start: float, end: float):
    return get_transcript_window(FakeRunContext(deps), start, end)


def test_the_transcript_window_is_read_with_a_moment_recorded_per_piece() -> None:
    pool = FakePool(responses=[SEGMENT_ROWS, OUTLINE_ROWS])
    deps = _deps(pool)

    result = _transcript(deps, 125.0, 145.0)

    assert isinstance(result, TranscriptWindow)
    assert [(piece.start_seconds, piece.end_seconds, piece.text) for piece in result.pieces] == [
        (128.0, 133.5, "Here is the diagram."),
        (133.5, 140.0, "Each box is a partition."),
    ]
    assert (result.start_seconds, result.end_seconds, result.chapter, result.note) == (
        125.0,
        145.0,
        "Kafka partitions",
        None,
    )
    assert deps.spans == [(128.0, 133.5), (133.5, 140.0)]
    # The store's overlap query binds the end before the start.
    assert pool.recorded[0].parameters == (VIDEO_ID, 145.0, 125.0)
    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (1, 0)


def test_a_window_longer_than_three_minutes_is_cut_to_its_first_three() -> None:
    pool = FakePool(responses=[[], OUTLINE_ROWS])
    deps = _deps(pool)

    result = _transcript(deps, 100.0, 400.0)

    assert MAX_WINDOW_SECONDS == 180.0
    assert (result.start_seconds, result.end_seconds) == (100.0, 280.0)
    assert result.note == "The window was cut to its first 180 seconds."
    assert pool.recorded[0].parameters == (VIDEO_ID, 280.0, 100.0)
    assert result.pieces == [] and deps.spans == []


def test_a_window_before_the_start_or_ending_before_it_starts_is_straightened() -> None:
    pool = FakePool(responses=[[], OUTLINE_ROWS])

    result = _transcript(_deps(pool), -10.0, -20.0)

    assert (result.start_seconds, result.end_seconds) == (0.0, 0.0)


def test_pieces_past_the_character_cap_are_left_out_and_uncitable() -> None:
    long_rows = [
        {"segment_index": index, "start_seconds": 10.0 * index, "end_seconds": 10.0 * index + 10.0, "text": "w" * 2500}
        for index in range(4)
    ]
    deps = _deps(FakePool(responses=[long_rows, OUTLINE_ROWS]))

    result = _transcript(deps, 0.0, 40.0)

    assert len(result.pieces) == 2
    assert result.note == "Only the first 2 pieces are given; the rest were too long."
    assert deps.spans == [(0.0, 10.0), (10.0, 20.0)]


def test_one_piece_longer_than_the_cap_is_still_given() -> None:
    deps = _deps(FakePool(responses=[[{"segment_index": 0, "start_seconds": 0.0, "end_seconds": 60.0, "text": "w" * 9000}], OUTLINE_ROWS]))

    result = _transcript(deps, 0.0, 60.0)

    assert len(result.pieces) == 1
    assert result.note is None


def test_after_six_calls_get_transcript_window_does_no_work() -> None:
    pool = FakePool(rows=[])
    deps = _deps(pool)

    results = [_transcript(deps, 0.0, 10.0) for _ in range(MAX_TOOL_CALLS + 1)]

    assert isinstance(results[-1], BudgetSpent)
    transcript_reads = sum("transcript_segments" in statement for statement in pool.statements)
    assert transcript_reads == MAX_TOOL_CALLS


def test_the_three_tools_share_one_budget() -> None:
    deps = _deps(FakePool(rows=[]), engine=None)

    _view(deps, [1.0, 2.0])
    _read_text(deps, [3.0])
    _transcript(deps, 0.0, 10.0)

    assert (deps.budget.tool_calls_used, deps.budget.images_used) == (3, 2)
