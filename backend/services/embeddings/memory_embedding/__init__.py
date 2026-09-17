"""Public interface of the memory embedding pipeline."""

from .pipeline import embed_memories_for_video
from .text import build_embedding_text

__all__ = [
    "build_embedding_text",
    "embed_memories_for_video",
]
