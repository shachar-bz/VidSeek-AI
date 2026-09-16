"""Public interface of the Azure Database for PostgreSQL module."""

from .comments import PostgresComments
from .connection import build_pool, connection, shared_pool
from .migrate import apply_migrations, migration_files, pending_migrations
from .settings import PostgresSettings, is_postgres_configured, load_postgres_settings
from .transcript_segments import PostgresTranscriptSegments
from .video_records import PostgresVideoRecords, StoredVideoRecord, VideoRecord

__all__ = [
    "PostgresComments",
    "PostgresSettings",
    "PostgresTranscriptSegments",
    "PostgresVideoRecords",
    "StoredVideoRecord",
    "VideoRecord",
    "apply_migrations",
    "build_pool",
    "connection",
    "is_postgres_configured",
    "load_postgres_settings",
    "migration_files",
    "pending_migrations",
    "shared_pool",
]
