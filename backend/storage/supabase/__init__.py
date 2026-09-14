"""Public interface of the Supabase database module."""

from .client import build_client, shared_client
from .settings import SupabaseSettings, is_supabase_configured, load_supabase_settings
from .transcript_segments import SupabaseTranscriptSegments
from .video_records import StoredVideoRecord, SupabaseVideoRecords, VideoRecord

__all__ = [
    "StoredVideoRecord",
    "SupabaseSettings",
    "SupabaseTranscriptSegments",
    "SupabaseVideoRecords",
    "VideoRecord",
    "build_client",
    "is_supabase_configured",
    "load_supabase_settings",
    "shared_client",
]
