"""Public interface of the Azure Database for PostgreSQL module.

`migrate` is deliberately not re-exported. It is a command-line entry point, run as
`python -m backend.storage.postgres.migrate`, and importing it here would load it once as
part of this package and again as `__main__`, which Python warns about and which would give
the runner two copies of its own module-level state. Import it by its full path instead.
"""

from .chapter_embeddings import ChapterEmbedding, ChapterForEmbedding, PostgresChapterEmbeddings
from .chapters import (
    ChapterHeading,
    ChapterWithNeighbours,
    NewChapter,
    PostgresChapters,
    StoredChapter,
    StoredChapterMemory,
    StoredChapterOutline,
)
from .comments import PostgresComments
from .connection import build_pool, connection, iso_text, shared_pool
from .conversations import PostgresConversations, StoredConversation
from .memories import NewMemory, PostgresMemories, StoredMemory
from .memory_embeddings import (
    MemoryEmbedding,
    MemoryForEmbedding,
    MemoryMatch,
    PostgresMemoryEmbeddings,
)
from .messages import PostgresMessages, StoredMessage
from .pinned_answers import PinnedAnswerForVideo, PostgresPinnedAnswers, StoredPinnedAnswer
from .sessions import PostgresSessions, StoredSession, hash_token
from .settings import PostgresSettings, is_postgres_configured, load_postgres_settings
from .transcript_segments import PostgresTranscriptSegments
from .user_videos import PostgresUserVideos, StoredUserVideo
from .users import NewUser, PostgresUsers, StoredUser
from .video_insights import NewVideoInsights, PostgresVideoInsights, StoredVideoInsights
from .video_jobs import PostgresVideoJobs, StoredVideoJob, VideoJob
from .video_records import PostgresVideoRecords, StoredVideoRecord, VideoRecord

__all__ = [
    "ChapterEmbedding",
    "ChapterForEmbedding",
    "ChapterHeading",
    "ChapterWithNeighbours",
    "MemoryEmbedding",
    "MemoryForEmbedding",
    "MemoryMatch",
    "NewChapter",
    "NewMemory",
    "NewUser",
    "NewVideoInsights",
    "PinnedAnswerForVideo",
    "PostgresChapterEmbeddings",
    "PostgresChapters",
    "PostgresComments",
    "PostgresConversations",
    "PostgresMemories",
    "PostgresMemoryEmbeddings",
    "PostgresMessages",
    "PostgresPinnedAnswers",
    "PostgresSessions",
    "PostgresSettings",
    "PostgresTranscriptSegments",
    "PostgresUserVideos",
    "PostgresUsers",
    "PostgresVideoInsights",
    "PostgresVideoJobs",
    "PostgresVideoRecords",
    "StoredChapter",
    "StoredChapterMemory",
    "StoredChapterOutline",
    "StoredConversation",
    "StoredMemory",
    "StoredMessage",
    "StoredPinnedAnswer",
    "StoredSession",
    "StoredUser",
    "StoredUserVideo",
    "StoredVideoInsights",
    "StoredVideoJob",
    "StoredVideoRecord",
    "VideoJob",
    "VideoRecord",
    "build_pool",
    "connection",
    "hash_token",
    "is_postgres_configured",
    "iso_text",
    "load_postgres_settings",
    "shared_pool",
]
