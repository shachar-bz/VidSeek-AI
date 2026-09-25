"""The OCR engine this machine is configured with, shared by every video the process indexes.

v1 has one engine, Surya, and it is optional: without `VIDSEEK_OCR_PYTHON` there is none, and
visual indexing leaves keyframes unread rather than failing. The engine is built once and its
worker kept, because starting one loads the OCR model; it is stopped when the process exits.
"""

from __future__ import annotations

import atexit
import threading

from backend.core import config

from .engine import OcrEngine
from .surya import SuryaOcrEngine

_build_lock = threading.Lock()
_shared: SuryaOcrEngine | None = None


def configured_ocr_engine() -> OcrEngine | None:
    """The process-wide engine, or None when OCR is not set up on this machine."""
    global _shared
    python_path = config.ocr_python_path()
    if python_path is None:
        return None
    with _build_lock:
        if _shared is None:
            _shared = SuryaOcrEngine(
                python_path, llama_server_path=config.ocr_llama_server_path()
            )
            atexit.register(_shared.close)
        return _shared
