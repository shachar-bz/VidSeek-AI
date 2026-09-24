"""multilingual-e5-small, loaded once per process: meaning vectors for on-screen text.

The shared all-MiniLM-L6-v2 (`backend/services/embeddings/model.py`) is English-only, and what
this model embeds -- the on-screen text OCR reads off keyframes -- is as often Hebrew as
English. It runs locally, like MiniLM.

e5 was trained with a role prefix on every input: `query: ` on what is searched for and
`passage: ` on what is searched through. Leaving the prefix off measurably worsens retrieval,
so the two roles have one function each rather than trusting callers to remember.

Encoding runs behind a lock for the reason `image_embedding` gives: the models share one small
GPU, and the indexing thread and a chat request may reach it at the same time.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"

# The model's output width; every column this model writes to is declared with it.
EMBEDDING_DIMENSIONS = 384

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

logger = logging.getLogger(__name__)

_build_lock = threading.Lock()
_encode_lock = threading.Lock()
_shared: SentenceTransformer | None = None


def shared_model() -> SentenceTransformer:
    """The process-wide model, built on first use and reused by every caller after."""
    global _shared
    with _build_lock:
        if _shared is None:
            _shared = SentenceTransformer(MODEL_NAME)
            logger.info("Loaded %s on %s", MODEL_NAME, _shared.device)
        return _shared


def embed_query(text: str, *, model: SentenceTransformer | None = None) -> list[float]:
    """One normalized vector for something being searched for."""
    return _encode([QUERY_PREFIX + text], model=model)[0]


def embed_passages(
    texts: Sequence[str], *, model: SentenceTransformer | None = None
) -> list[list[float]]:
    """One normalized vector per piece of text being searched through, in order."""
    if not texts:
        return []
    return _encode([PASSAGE_PREFIX + text for text in texts], model=model)


def _encode(texts: list[str], *, model: SentenceTransformer | None) -> list[list[float]]:
    resolved = model or shared_model()
    with _encode_lock:
        vectors = resolved.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vectors.tolist()
