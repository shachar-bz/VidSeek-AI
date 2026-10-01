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
from .comment_embeddings import CommentEmbedding, PostgresCommentEmbeddings
from .comments import PostgresComments
from .connection import build_pool, connection, iso_text, shared_pool
from .conversations import PostgresConversations, StoredConversation
from .memories import NewMemory, PostgresMemories, StoredMemory
from .memory_embeddings import (
    MemoryEmbedding,
    MemoryForEmbedding,
    PostgresMemoryEmbeddings,
    ScoredMemory,
)
from .library_views import LibraryViewRow, PostgresLibraryViews
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
from .visual_index import (
    FrameSimilarity,
    KeyframeText,
    KeyframeTextMatch,
    NewFrameEmbedding,
    NewVisualSegment,
    PostgresVisualIndex,
    StoredKeyframe,
    StoredKeyframeText,
    StoredVisualSegment,
    VisualIndexState,
)

__all__ = [
    "ChapterEmbedding",
    "ChapterForEmbedding",
    "ChapterHeading",
    "ChapterWithNeighbours",
    "CommentEmbedding",
    "FrameSimilarity",
    "KeyframeText",
    "KeyframeTextMatch",
    "MemoryEmbedding",
    "MemoryForEmbedding",
    "LibraryViewRow",
    "NewChapter",
    "NewFrameEmbedding",
    "NewMemory",
    "NewUser",
    "NewVideoInsights",
    "NewVisualSegment",
    "PinnedAnswerForVideo",
    "PostgresChapterEmbeddings",
    "PostgresChapters",
    "PostgresCommentEmbeddings",
    "PostgresComments",
    "PostgresConversations",
    "PostgresMemories",
    "PostgresMemoryEmbeddings",
    "PostgresLibraryViews",
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
    "PostgresVisualIndex",
    "ScoredMemory",
    "StoredChapter",
    "StoredChapterMemory",
    "StoredChapterOutline",
    "StoredConversation",
    "StoredMemory",
    "StoredMessage",
    "StoredPinnedAnswer",
    "StoredSession",
    "StoredUser",
    "StoredKeyframe",
    "StoredKeyframeText",
    "StoredUserVideo",
    "StoredVideoInsights",
    "StoredVideoJob",
    "StoredVideoRecord",
    "StoredVisualSegment",
    "VideoJob",
    "VideoRecord",
    "VisualIndexState",
    "build_pool",
    "connection",
    "hash_token",
    "is_postgres_configured",
    "iso_text",
    "load_postgres_settings",
    "shared_pool",
]
