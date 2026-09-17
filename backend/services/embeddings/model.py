"""Shared all-MiniLM-L6-v2 sentence-transformers model, loaded once per process.

Every caller that needs to embed text imports `shared_model` (or the `embed_text`
wrapper) rather than constructing its own `SentenceTransformer`, so the checkpoint is
loaded into memory once no matter how many modules embed text. It runs locally: no API
key, no per-call cost, and the GPU is used automatically when one is available.
"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

# The model's native output size; any embedding column this model writes to must be
# declared with this dimension.
EMBEDDING_DIMENSIONS = 384


def build_model() -> SentenceTransformer:
    """Load a fresh instance of the embedding model."""
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def shared_model() -> SentenceTransformer:
    """The process-wide model, so the checkpoint is loaded once and reused everywhere.

    Safe to share across threads once built; `build_model` stays available for a test
    or anywhere else that needs an isolated instance.
    """
    return build_model()


def embed_text(text: str, *, model: SentenceTransformer | None = None) -> list[float]:
    """Embed one piece of text into a 384-dimensional vector."""
    resolved = model or shared_model()
    return resolved.encode(text, convert_to_numpy=True).tolist()
