"""Loads the embedding models in the background when the API starts, so no user waits for them."""

from __future__ import annotations

import logging
import threading

from backend.core import config

logger = logging.getLogger(__name__)


def start_model_preload() -> threading.Thread | None:
    """Start loading the models on a daemon thread, or do nothing when preloading is off.

    The thread keeps the server's start-up quick and the event loop free. A request that
    arrives before a model is ready waits for the same load, because each model is built
    once behind its own lock.
    """
    if not config.model_preload_enabled():
        return None
    thread = threading.Thread(target=_load_models, name="vidseek-model-preload", daemon=True)
    thread.start()
    return thread


def _load_models() -> None:
    """Build the text model first, since every chat question needs it, then SigLIP 2.

    A model that fails to load is logged and left to load on first use, so a broken download
    cannot keep the API from serving the questions that do not need it. SigLIP 2 is loaded
    only when visual indexing is on, because a machine that turned it off has no visual index
    to search. The imports sit here because importing torch and the model libraries is itself
    slow, and doing it at the top of the module would hold up the server's start.
    """
    try:
        from backend.services.embeddings.multilingual_text_embedding.model import shared_model

        shared_model()
    except Exception:
        logger.exception("Could not preload the text embedding model; it loads on first use")
    if not config.visual_indexing_enabled():
        return
    try:
        from backend.services.embeddings.image_embedding import shared_encoder

        shared_encoder()
    except Exception:
        logger.exception("Could not preload the image embedding model; it loads on first use")
