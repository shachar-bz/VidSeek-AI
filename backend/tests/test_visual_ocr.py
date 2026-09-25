"""Tests for OCR in visual indexing: what a keyframe keeps of a reading, and the Surya engine's plumbing.

Surya itself is not installed in the backend's environment, so nothing here runs it. The
engine is tested against a stand-in worker -- a few lines of Python speaking the same
protocol, run with this interpreter -- which is what the engine's own job is: starting a
worker, talking to it, and recovering when it misbehaves. The worker's page logic is tested
with stand-ins for Surya's two predictors.
"""

import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.services.visual_indexing import SamplingStopped, keyframe_text, read_keyframe_text
from backend.services.ocr import (
    ENGLISH,
    HEBREW,
    MIXED,
    OTHER,
    FrameReading,
    OcrError,
    TextBlock,
    configured_ocr_engine,
    on_screen_text,
    script_language,
)
from backend.services.ocr.surya import ENGINE_NAME, SuryaOcrEngine, html_to_text
from backend.services.ocr.surya import worker as surya_worker
from backend.services.ocr.surya.engine import WORKER_ENVIRONMENT_DEFAULTS


def frame(colour: str = "white") -> Image.Image:
    return Image.new("RGB", (64, 36), colour)


# --- what a keyframe keeps -----------------------------------------------------------------


def test_blocks_are_joined_in_reading_order_one_per_line_with_their_spacing_tidied() -> None:
    reading = FrameReading(
        blocks=(
            TextBlock("  System   design \n\n", "SectionHeader", 0.9),
            TextBlock("Load balancer\n  Cache  ", "Text", 0.8),
        )
    )

    text = on_screen_text(reading)

    assert text.text == "System design\nLoad balancer\nCache"
    assert text.language == ENGLISH


def test_a_block_the_engine_was_unsure_of_is_dropped_and_confidence_is_weighted_by_length() -> None:
    reading = FrameReading(
        blocks=(
            TextBlock("A long paragraph read well", "Text", 0.9),
            TextBlock("p3", "PageFooter", 0.3),
            TextBlock("Short", "Text", 0.6),
        )
    )

    text = on_screen_text(reading)

    assert text.text == "A long paragraph read well\nShort"
    assert text.confidence == pytest.approx((0.9 * 26 + 0.6 * 5) / 31)


def test_a_frame_with_no_text_worth_keeping_keeps_none() -> None:
    assert on_screen_text(FrameReading()) is None
    assert on_screen_text(FrameReading(blocks=(TextBlock("   ", "Text", 0.9),))) is None
    assert on_screen_text(FrameReading(blocks=(TextBlock("noise", "Text", 0.2),))) is None


def test_a_block_without_a_confidence_is_kept_and_leaves_none_to_average() -> None:
    text = on_screen_text(FrameReading(blocks=(TextBlock("Agenda", "Text"),)))

    assert (text.text, text.confidence) == ("Agenda", None)


def test_the_language_is_decided_by_the_script_of_the_letters() -> None:
    assert script_language("ארכיטקטורה של המערכת") == HEBREW
    # Digits and symbols count for neither, so a Hebrew slide of numbers stays Hebrew.
    assert script_language("תוצאות 2024: 45% ↑") == HEBREW
    assert script_language("Kubernetes cluster") == ENGLISH
    assert script_language("שלב ראשון: Deploy") == MIXED
    # A Hebrew word in an English slide is still an English slide.
    assert script_language("שלב 1: Deploy to Kubernetes") == ENGLISH
    assert script_language("Привет мир") == OTHER
    assert script_language("12:30 — 45%") is None


# --- Surya's HTML --------------------------------------------------------------------------


def test_surya_html_becomes_lines_of_text_with_entities_decoded() -> None:
    html = "<h1>Q3 &amp; Q4</h1><p>First line<br>second line</p><ul><li>one</li><li>two</li></ul>"

    assert html_to_text(html).splitlines() == ["Q3 & Q4", "First line", "second line", "one", "two"]


def test_table_cells_are_set_apart_and_math_is_kept_as_written() -> None:
    text = html_to_text("<table><tr><td>a</td><td>b</td></tr></table><math>x^2</math>")

    assert "a  b" in text
    assert "x^2" in text


# --- the worker's page logic ---------------------------------------------------------------


class StandInDetector:
    def __init__(self, lines_per_image):
        self._lines = lines_per_image

    def __call__(self, images):
        return [SimpleNamespace(bboxes=[object()] * count) for count in self._lines]


class StandInRecognizer:
    def __init__(self):
        self.seen = []

    def __call__(self, images, *, full_page):
        self.seen.append((len(images), full_page))
        block = lambda order, html, **flags: SimpleNamespace(
            reading_order=order,
            html=html,
            label="Text",
            confidence=0.9,
            skipped=flags.get("skipped", False),
            error=flags.get("error", False),
        )
        return [
            SimpleNamespace(
                blocks=[
                    block(1, "<p>second</p>"),
                    block(0, "<h1>first</h1>"),
                    block(2, "", skipped=True),
                    block(3, "<p>lost</p>", error=True),
                ]
            )
            for _ in images
        ]


def test_the_worker_reads_only_frames_the_detector_found_text_on() -> None:
    recognizer = StandInRecognizer()

    pages = surya_worker.read_pages([frame(), frame(), frame()], StandInDetector([0, 3, 0]), recognizer)

    assert recognizer.seen == [(1, True)]
    assert pages[0] == {"blocks": []} and pages[2] == {"blocks": []}
    # Reading order, and neither a skipped picture nor a failed block.
    assert [block["html"] for block in pages[1]["blocks"]] == ["<h1>first</h1>", "<p>second</p>"]


def test_the_worker_never_calls_the_ocr_model_for_frames_with_no_text() -> None:
    recognizer = StandInRecognizer()

    pages = surya_worker.read_pages([frame(), frame()], StandInDetector([0, 0]), recognizer)

    assert pages == [{"blocks": []}, {"blocks": []}]
    assert recognizer.seen == []


# --- the engine, against a stand-in worker -------------------------------------------------

# Speaks the worker's protocol. Each image it is sent comes back as one block whose HTML
# names its width, so a test can tell the pages apart and check their order.
STAND_IN_WORKER = textwrap.dedent(
    """
    import base64, io, json, os, sys, time
    from PIL import Image

    mode = sys.argv[1]
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n")
        sys.stdout.flush()

    if mode == "fatal":
        send({"fatal": "RuntimeError: llama-server binary not found"})
        sys.exit(1)
    print("loading models", file=sys.stderr, flush=True)
    send({"ready": True, "surya_version": "0.0-test", "pid": os.getpid()})
    for line in sys.stdin:
        request = json.loads(line)
        if mode == "crash":
            print("Segmentation fault", file=sys.stderr, flush=True)
            sys.exit(3)
        if mode == "hang":
            time.sleep(60)
        if mode == "refuse":
            send({"id": request["id"], "error": "ValueError: cannot read"})
            continue
        if mode == "out_of_step":
            send({"id": request["id"] + 100, "pages": []})
            continue
        pages = []
        for encoded in request["images"]:
            width = Image.open(io.BytesIO(base64.b64decode(encoded))).width
            pages.append({"blocks": [
                {"html": f"<p>width {width} &amp; pid {os.getpid()}</p>", "label": "Text", "confidence": 0.9},
                {"html": "", "label": "Text", "confidence": 0.9},
            ]})
        send({"id": request["id"], "pages": pages})
    """
)


def stand_in_engine(tmp_path: Path, mode: str = "ok", **options) -> SuryaOcrEngine:
    script = tmp_path / "stand_in_worker.py"
    script.write_text(STAND_IN_WORKER, encoding="utf-8")
    return SuryaOcrEngine(worker_command=[sys.executable, str(script), mode], **options)


def worker_pid(reading: FrameReading) -> str:
    return reading.blocks[0].text.rsplit("pid ", 1)[1]


def test_the_engine_answers_one_reading_per_frame_in_order(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path)
    try:
        readings = engine.read([Image.new("RGB", (40, 10)), Image.new("RGB", (80, 10))])
    finally:
        engine.close()

    assert [reading.blocks[0].text.split(" &")[0] for reading in readings] == [
        "width 40",
        "width 80",
    ]
    # HTML turned to text, and the empty block dropped.
    assert readings[0].blocks[0].text.startswith("width 40 & pid")
    assert len(readings[0].blocks) == 1
    assert readings[0].blocks[0].confidence == 0.9
    assert engine.name == ENGINE_NAME == "surya-ocr-2"


def test_the_worker_is_started_once_and_reused(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path)
    try:
        first = engine.read([frame()])
        second = engine.read([frame()])
    finally:
        engine.close()

    assert worker_pid(first[0]) == worker_pid(second[0])


def test_no_frames_start_no_worker(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="fatal")

    assert engine.read([]) == []


def test_a_worker_that_cannot_load_surya_says_why(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="fatal")

    with pytest.raises(OcrError, match="llama-server binary not found"):
        engine.read([frame()])


def test_a_crashed_worker_is_reported_with_its_last_words_and_replaced(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="crash")

    with pytest.raises(OcrError, match="Segmentation fault"):
        engine.read([frame()])
    # The next read starts a fresh worker rather than writing to a dead one.
    with pytest.raises(OcrError, match="exited"):
        engine.read([frame()])


def test_a_worker_that_does_not_answer_in_time_is_stopped(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="hang", read_timeout_seconds=0.5)

    with pytest.raises(OcrError, match="no answer in 0.5 s"):
        engine.read([frame()])
    assert engine._worker is None


def test_a_request_the_worker_could_not_read_keeps_the_worker(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="refuse")
    try:
        with pytest.raises(OcrError, match="cannot read"):
            engine.read([frame()])
        assert engine._worker is not None and engine._worker.alive()
    finally:
        engine.close()


def test_an_answer_out_of_step_stops_the_worker(tmp_path: Path) -> None:
    engine = stand_in_engine(tmp_path, mode="out_of_step")

    with pytest.raises(OcrError, match="answered request"):
        engine.read([frame()])
    assert engine._worker is None


def test_a_missing_ocr_interpreter_is_named(tmp_path: Path) -> None:
    engine = SuryaOcrEngine(tmp_path / "no-such-python.exe")

    with pytest.raises(OcrError, match="VIDSEEK_OCR_PYTHON"):
        engine.read([frame()])


def test_the_worker_runs_surya_the_way_the_small_gpu_needs_unless_told_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SURYA_INFERENCE_PARALLEL", "1")
    engine = SuryaOcrEngine(tmp_path / "python.exe", llama_server_path="C:/llama/llama-server.exe")

    environment = engine._environment()

    assert environment["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert environment["TORCH_DEVICE"] == "cpu"
    assert environment["SURYA_INFERENCE_PARALLEL"] == "1"
    assert environment["LLAMA_CPP_BINARY"] == "C:/llama/llama-server.exe"
    assert set(WORKER_ENVIRONMENT_DEFAULTS) <= set(environment)


def test_ocr_is_off_until_an_interpreter_is_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert configured_ocr_engine() is None

    monkeypatch.setenv("VIDSEEK_OCR_PYTHON", str(tmp_path / "python.exe"))

    assert isinstance(configured_ocr_engine(), SuryaOcrEngine)
    assert configured_ocr_engine() is configured_ocr_engine()


# --- reading a video's keyframes -----------------------------------------------------------


class RecordingEngine:
    """Reads a frame's colour as its text: white frames show "slide", black ones nothing."""

    name = "recording-engine"

    def __init__(self):
        self.batches = []

    def read(self, images):
        self.batches.append(len(images))
        return [
            FrameReading(blocks=(TextBlock("slide", "Text", 0.9),))
            if image.getpixel((0, 0)) == (255, 255, 255)
            else FrameReading()
            for image in images
        ]


def test_keyframes_are_read_in_batches_in_time_order_and_past_the_end_is_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = {0.0: frame("white"), 2.0: frame("black"), 60.0: frame("white"), 90.0: None}
    monkeypatch.setattr(keyframe_text, "decode_frame_at", lambda path, time_seconds: frames[time_seconds])
    engine = RecordingEngine()

    batches = list(read_keyframe_text(Path("video.mp4"), [60.0, 0.0, 2.0, 90.0, 0.0], engine, batch_size=2))

    assert engine.batches == [2, 1]
    readings = [reading for batch in batches for reading in batch]
    assert [reading.time_seconds for reading in readings] == [0.0, 2.0, 60.0]
    assert [reading.text.text if reading.text else None for reading in readings] == ["slide", None, "slide"]


def test_reading_keyframes_stops_between_batches_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyframe_text, "decode_frame_at", lambda path, time_seconds: frame())
    stop = threading.Event()
    readings = read_keyframe_text(Path("video.mp4"), [0.0, 2.0, 4.0], RecordingEngine(), batch_size=1, stop_event=stop)

    next(readings)
    stop.set()

    with pytest.raises(SamplingStopped):
        next(readings)
