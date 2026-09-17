"""Public interface of the Azure Database for PostgreSQL module.

`migrate` is deliberately not re-exported. It is a command-line entry point, run as
`python -m backend.storage.postgres.migrate`, and importing it here would load it once as
part of this package and again as `__main__`, which Python warns about and which would give
the runner two copies of its own module-level state. Import it by its full path instead.
"""

from .chapter_embeddings import ChapterEmbedding, ChapterForEmbedding, PostgresChapterEmbeddings
from .comments import PostgresComments
from .connection import build_pool, connection, iso_text, shared_pool
from .memory_embeddings import (
    MemoryEmbedding,
    MemoryForEmbedding,
    MemoryMatch,
    PostgresMemoryEmbeddings,
)
from .settings import PostgresSettings, is_postgres_configured, load_postgres_settings
from .transcript_segments import PostgresTranscriptSegments
from .users import NewUser, PostgresUsers, StoredUser
from .video_records import PostgresVideoRecords, StoredVideoRecord, VideoRecord

__all__ = [
    "ChapterEmbedding",
    "ChapterForEmbedding",
    "MemoryEmbedding",
    "MemoryForEmbedding",
    "MemoryMatch",
    "NewUser",
    "PostgresChapterEmbeddings",
    "PostgresComments",
    "PostgresMemoryEmbeddings",
    "PostgresSettings",
    "PostgresTranscriptSegments",
    "PostgresUsers",
    "PostgresVideoRecords",
    "StoredUser",
    "StoredVideoRecord",
    "VideoRecord",
    "build_pool",
    "connection",
    "is_postgres_configured",
    "iso_text",
    "load_postgres_settings",
    "shared_pool",
]
