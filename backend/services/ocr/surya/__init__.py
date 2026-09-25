"""Public interface of the Surya OCR engine. `worker.py` is not imported: it runs in Surya's own environment."""

from .engine import ENGINE_NAME, SuryaOcrEngine
from .html_text import html_to_text

__all__ = ["ENGINE_NAME", "SuryaOcrEngine", "html_to_text"]
