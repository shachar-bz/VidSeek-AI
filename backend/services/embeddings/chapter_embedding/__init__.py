"""Public interface of the chapter embedding pipeline."""

from .pipeline import embed_chapters_for_video
from .text import build_embedding_text

__all__ = [
    "build_embedding_text",
    "embed_chapters_for_video",
]
