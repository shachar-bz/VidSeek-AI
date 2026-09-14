"""Public interface of the Cloudflare R2 video storage module."""

from .client import build_client, shared_client
from .settings import R2Settings, is_r2_configured, load_r2_settings
from .video_storage import R2VideoStorage, StoredVideo, build_video_key

__all__ = [
    "R2Settings",
    "R2VideoStorage",
    "StoredVideo",
    "build_client",
    "build_video_key",
    "is_r2_configured",
    "load_r2_settings",
    "shared_client",
]
