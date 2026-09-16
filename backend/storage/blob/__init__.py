"""Public interface of the Azure Blob Storage video module."""

from .client import build_client, shared_client
from .settings import BlobSettings, is_blob_configured, load_blob_settings
from .video_storage import BlobVideoStorage, StoredVideo, build_video_key

__all__ = [
    "BlobSettings",
    "BlobVideoStorage",
    "StoredVideo",
    "build_client",
    "build_video_key",
    "is_blob_configured",
    "load_blob_settings",
    "shared_client",
]
