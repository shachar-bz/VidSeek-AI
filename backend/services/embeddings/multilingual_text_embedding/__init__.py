"""Public interface of the multilingual-e5-small text embedding module."""

from .model import EMBEDDING_DIMENSIONS, MODEL_NAME, embed_passages, embed_query, shared_model

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "MODEL_NAME",
    "embed_passages",
    "embed_query",
    "shared_model",
]
