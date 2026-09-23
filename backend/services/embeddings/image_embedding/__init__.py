"""Public interface of the SigLIP 2 image embedding module."""

from .model import (
    EMBEDDING_DIMENSIONS,
    MODEL_NAME,
    SiglipEncoder,
    shared_encoder,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "MODEL_NAME",
    "SiglipEncoder",
    "shared_encoder",
]
