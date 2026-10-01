"""The API's start-up preload loads the embedding models only when configured to."""

from backend.api import model_preload
from backend.services.embeddings import image_embedding
from backend.services.embeddings.multilingual_text_embedding import model as text_model


def _record_loads(monkeypatch) -> list[str]:
    loaded: list[str] = []
    monkeypatch.setattr(text_model, "shared_model", lambda: loaded.append("text"))
    monkeypatch.setattr(image_embedding, "shared_encoder", lambda: loaded.append("image"))
    return loaded


def test_preload_loads_both_models_when_visual_indexing_is_on(monkeypatch):
    monkeypatch.setenv("VIDSEEK_PRELOAD_MODELS", "true")
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    loaded = _record_loads(monkeypatch)

    thread = model_preload.start_model_preload()
    thread.join(timeout=5)

    assert loaded == ["text", "image"]


def test_preload_skips_the_image_model_when_visual_indexing_is_off(monkeypatch):
    monkeypatch.setenv("VIDSEEK_PRELOAD_MODELS", "true")
    loaded = _record_loads(monkeypatch)

    thread = model_preload.start_model_preload()
    thread.join(timeout=5)

    assert loaded == ["text"]


def test_preload_does_nothing_when_turned_off(monkeypatch):
    loaded = _record_loads(monkeypatch)

    assert model_preload.start_model_preload() is None
    assert loaded == []


def test_a_model_that_fails_to_load_does_not_stop_the_other(monkeypatch):
    monkeypatch.setenv("VIDSEEK_PRELOAD_MODELS", "true")
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "true")
    loaded = _record_loads(monkeypatch)

    def fail():
        raise RuntimeError("download failed")

    monkeypatch.setattr(text_model, "shared_model", fail)

    thread = model_preload.start_model_preload()
    thread.join(timeout=5)

    assert loaded == ["image"]
