"""SigLIP 2 (base), loaded once per process: image vectors for frames, text vectors for queries.

SigLIP 2 puts images and text in one space, so a frame embedded while a video is indexed can
be scored later against a question typed in chat -- in Hebrew as well as English, since the
model was trained on multilingual captions. It runs locally: no API key and no per-call cost.

One model object serves two threads. The visual indexing thread embeds batches of frames
while a chat request may need a query vector, so every forward pass runs behind one lock:
they take turns on the GPU instead of both allocating on a 4 GB card at once. The model is
built behind a second lock so two first callers cannot load two copies.

Both encoders return L2-normalized vectors, so a dot product -- and pgvector's `<=>` -- is
cosine similarity.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

MODEL_NAME = "google/siglip2-base-patch16-256"

# The width of both towers' output; `video_frame_embeddings.embedding` is declared with it.
EMBEDDING_DIMENSIONS = 768

# SigLIP 2 was trained on text padded to exactly 64 tokens. Anything else changes the
# vector a query gets, so the processor is asked for that shape every time.
TEXT_MAX_LENGTH = 64

# Frames per forward pass while indexing. A batch this size peaks at about 1.8 GB on the GTX
# 1650, weights included, which leaves room for the other resident models in its 4 GB.
IMAGE_BATCH_SIZE = 32

logger = logging.getLogger(__name__)

_build_lock = threading.Lock()
_shared: SiglipEncoder | None = None


class SiglipEncoder:
    """The SigLIP 2 image and text towers, and the lock their forward passes share."""

    def __init__(self, model_name: str = MODEL_NAME, device: str | None = None):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        # Full precision, on the GPU as well. Half precision would halve the weights, but the
        # GTX 1650 has no tensor cores and measured 2.6x slower in it (32 frames in 4.8 s
        # against 1.8 s), which is a slower index for memory the card does not need back.
        self._dtype = torch.float32
        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = (
            AutoModel.from_pretrained(model_name, dtype=self._dtype).to(self.device).eval()
        )
        self._lock = threading.Lock()
        logger.info("Loaded %s on %s", model_name, self.device)

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        """One normalized vector per image, as a `(len(images), 768)` float32 array."""
        if not images:
            return np.zeros((0, EMBEDDING_DIMENSIONS), dtype=np.float32)
        batches = []
        for start in range(0, len(images), IMAGE_BATCH_SIZE):
            batch = [image.convert("RGB") for image in images[start : start + IMAGE_BATCH_SIZE]]
            inputs = self._processor(images=batch, return_tensors="pt")
            with self._lock, torch.inference_mode():
                pixel_values = inputs["pixel_values"].to(self.device, dtype=self._dtype)
                features = _pooled(self._model.get_image_features(pixel_values=pixel_values))
                batches.append(_normalized(features))
        return np.concatenate(batches, axis=0)

    def embed_text(self, text: str) -> list[float]:
        """One normalized vector for a search query, comparable to the frame vectors.

        Lower-cased first, because SigLIP 2 was trained on lower-cased text; Hebrew has no
        case, so this changes nothing there.
        """
        inputs = self._processor(
            text=[text.lower()],
            padding="max_length",
            max_length=TEXT_MAX_LENGTH,
            truncation=True,
            return_tensors="pt",
        )
        with self._lock, torch.inference_mode():
            features = _pooled(
                self._model.get_text_features(input_ids=inputs["input_ids"].to(self.device))
            )
            return _normalized(features)[0].tolist()


def shared_encoder() -> SiglipEncoder:
    """The process-wide encoder, built on first use and reused by every caller after."""
    global _shared
    with _build_lock:
        if _shared is None:
            _shared = SiglipEncoder()
        return _shared


def _pooled(output) -> torch.Tensor:
    """The pooled embedding, whether the model returned a tensor or a model output."""
    if isinstance(output, torch.Tensor):
        return output
    return output.pooler_output


def _normalized(features: torch.Tensor) -> np.ndarray:
    """Unit-length rows as a float32 numpy array."""
    return torch.nn.functional.normalize(features.float(), dim=-1).cpu().numpy()
