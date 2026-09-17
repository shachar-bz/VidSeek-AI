"""Public interface of the shared embeddings module."""

from .model import EMBEDDING_DIMENSIONS, MODEL_NAME, build_model, embed_text, shared_model

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "MODEL_NAME",
    "build_model",
    "embed_text",
    "shared_model",
]
