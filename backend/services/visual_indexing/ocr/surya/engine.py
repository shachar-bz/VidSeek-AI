"""Surya OCR behind the `OcrEngine` interface, run in a worker process of its own environment.

Surya cannot be imported here. It needs torch >= 2.7 and Pillow < 11, and the backend runs on
torch 2.6 and Pillow 12, so it lives in a separate environment (`requirements.txt`) and
`worker.py` is started with that environment's interpreter. The two sides speak one JSON
message per line over the worker's stdin and stdout; frames cross as base64 PNGs, lossless,
because a JPEG's ringing around thin strokes is exactly what OCR misreads.

One worker is kept for the life of the process. Starting one is slow -- the text detector
loads, and Surya starts `llama-server` with its OCR model, downloading the model from Hugging
Face the first time -- so it is started on the first read and reused by every video after.
A worker that crashes, times out or answers out of step is stopped, and the next read starts a
fresh one; a request the worker merely failed to read is reported and the worker kept.

The worker's environment is set so Surya fits the developer machine (GTX 1650, 4 GB):
llama.cpp rather than vLLM, which needs Docker and claims most of the card; two parallel
slots, since each slot keeps a KV cache of its own; the text detector on the CPU, leaving the
GPU to SigLIP and the OCR model. Any of them can be overridden in the process environment.
"""

from __future__ import annotations

import base64
import io
import itertools
import json
import logging
import os
import queue
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from ..engine import FrameReading, OcrError, TextBlock
from .html_text import html_to_text

# What every keyframe it read records as its engine: Surya 2's OCR model.
ENGINE_NAME = "surya-ocr-2"

WORKER_SCRIPT = Path(__file__).with_name("worker.py")

# The first start downloads the OCR model and the text detector, and llama-server then loads
# the model onto the GPU. Later starts take seconds.
STARTUP_TIMEOUT_SECONDS = 1800.0

# How long one batch of frames may take. A text-heavy frame is a long decode for a VLM on a
# small GPU; Surya's own request timeout is the same.
READ_TIMEOUT_SECONDS = 600.0

# How long a worker asked to stop is given to stop llama-server and exit before it is killed.
STOP_TIMEOUT_SECONDS = 30.0

# Set in the worker's environment unless the process environment already sets them.
WORKER_ENVIRONMENT_DEFAULTS = {
    "SURYA_INFERENCE_BACKEND": "llamacpp",
    "SURYA_INFERENCE_PARALLEL": "2",
    "TORCH_DEVICE": "cpu",
    "DISABLE_TQDM": "true",
    "PYTHONUNBUFFERED": "1",
}

# How much of the worker's stderr is kept to explain a failure.
STDERR_TAIL_BYTES = 8192

logger = logging.getLogger(__name__)


class SuryaOcrEngine:
    """Reads frames with Surya, through one long-lived worker process."""

    name = ENGINE_NAME

    def __init__(
        self,
        python_path: Path | None = None,
        *,
        llama_server_path: str | None = None,
        worker_command: Sequence[str] | None = None,
        startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS,
        read_timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ):
        """`python_path` is the OCR environment's interpreter; `worker_command` replaces
        `python_path worker.py` altogether, for a test to stand in for Surya."""
        if worker_command is None and python_path is None:
            raise ValueError("SuryaOcrEngine needs the OCR environment's python_path")
        self._command = list(worker_command or [str(python_path), str(WORKER_SCRIPT)])
        self._python_path = None if worker_command else python_path
        self._llama_server_path = llama_server_path
        self._startup_timeout = startup_timeout_seconds
        self._read_timeout = read_timeout_seconds
        self._worker: _WorkerProcess | None = None
        self._request_ids = itertools.count(1)
        self._lock = threading.Lock()

    def read(self, images: Sequence[Image.Image]) -> list[FrameReading]:
        """One reading per image, in order. Raises `OcrError` when the batch could not be read."""
        if not images:
            return []
        with self._lock:
            worker = self._running_worker()
            request_id = next(self._request_ids)
            try:
                worker.send({"id": request_id, "images": [_png_base64(image) for image in images]})
                reply = worker.receive(self._read_timeout)
                if reply.get("id") != request_id:
                    raise OcrError(f"Surya's worker answered request {reply.get('id')} to {request_id}")
            except OcrError:
                self._stop_worker(graceful=False)
                raise
            if "error" in reply:
                raise OcrError(f"Surya could not read the frames: {reply['error']}")
            pages = reply.get("pages")
            if not isinstance(pages, list) or len(pages) != len(images):
                self._stop_worker(graceful=False)
                raise OcrError("Surya's worker did not answer with one page per frame")
            return [_reading(page) for page in pages]

    def close(self) -> None:
        """Stop the worker, which stops llama-server with it. The next read starts a new one."""
        with self._lock:
            self._stop_worker()

    def _running_worker(self) -> _WorkerProcess:
        if self._worker is not None and self._worker.alive():
            return self._worker
        self._stop_worker()
        if self._python_path is not None and not self._python_path.is_file():
            raise OcrError(
                f"VIDSEEK_OCR_PYTHON points at {self._python_path}, which does not exist"
            )
        worker = _WorkerProcess(self._command, self._environment())
        try:
            hello = worker.receive(self._startup_timeout)
        except OcrError:
            worker.stop(graceful=False)
            raise
        if not hello.get("ready"):
            worker.stop(graceful=False)
            raise OcrError(f"Surya could not start: {hello.get('fatal') or hello}")
        logger.info("Started Surya %s for OCR", hello.get("surya_version", "(unknown version)"))
        self._worker = worker
        return worker

    def _stop_worker(self, *, graceful: bool = True) -> None:
        if self._worker is not None:
            self._worker.stop(graceful=graceful)
            self._worker = None

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        for name, value in WORKER_ENVIRONMENT_DEFAULTS.items():
            environment.setdefault(name, value)
        if self._llama_server_path:
            environment["LLAMA_CPP_BINARY"] = self._llama_server_path
        return environment


class _WorkerProcess:
    """The worker's process, its stdout read line by line on a thread, its stderr drained."""

    def __init__(self, command: list[str], environment: dict[str, str]):
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
        except OSError as error:
            raise OcrError(f"Surya's worker could not be started: {error}") from error
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._stderr_tail = bytearray()
        threading.Thread(target=self._read_stdout, name="surya-stdout", daemon=True).start()
        threading.Thread(target=self._drain_stderr, name="surya-stderr", daemon=True).start()

    def alive(self) -> bool:
        return self._process.poll() is None

    def send(self, message: dict) -> None:
        try:
            self._process.stdin.write(json.dumps(message).encode("ascii") + b"\n")
            self._process.stdin.flush()
        except OSError as error:
            raise OcrError(self._explain("stopped taking requests")) from error

    def receive(self, timeout_seconds: float) -> dict:
        try:
            line = self._lines.get(timeout=timeout_seconds)
        except queue.Empty:
            raise OcrError(f"Surya's worker gave no answer in {timeout_seconds:g} s") from None
        if line is None:
            raise OcrError(self._explain("exited"))
        try:
            message = json.loads(line)
        except ValueError:
            raise OcrError("Surya's worker wrote a line that is not a message") from None
        if not isinstance(message, dict):
            raise OcrError("Surya's worker wrote a line that is not a message")
        return message

    def stop(self, *, graceful: bool = True) -> None:
        """Close stdin, which ends the worker's loop, and kill it if it does not exit in time.

        A worker that already failed -- crashed, hung, answered out of step -- is killed at
        once rather than waited for. Surya then has no chance to stop its llama-server, which
        is left running; the next worker attaches to it instead of starting another.
        """
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.wait(timeout=STOP_TIMEOUT_SECONDS if graceful else 0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

    def _read_stdout(self) -> None:
        for line in iter(self._process.stdout.readline, b""):
            if line.strip():
                self._lines.put(line)
        self._lines.put(None)

    def _drain_stderr(self) -> None:
        for line in iter(self._process.stderr.readline, b""):
            logger.debug("surya: %s", line.decode("utf-8", errors="replace").rstrip())
            self._stderr_tail.extend(line)
            del self._stderr_tail[:-STDERR_TAIL_BYTES]

    def _explain(self, what_happened: str) -> str:
        detail = bytes(self._stderr_tail).decode("utf-8", errors="replace").strip()
        last_lines = "\n".join(detail.splitlines()[-5:])
        return f"Surya's worker {what_happened}" + (f": {last_lines}" if last_lines else "")


def _png_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _reading(page: dict) -> FrameReading:
    """One page of the worker's answer as the engine-neutral reading."""
    blocks = []
    for block in page.get("blocks") or ():
        text = html_to_text(block.get("html") or "")
        if text.strip():
            confidence = block.get("confidence")
            blocks.append(
                TextBlock(
                    text=text,
                    label=block.get("label") or "",
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
    return FrameReading(blocks=tuple(blocks))
