"""The `chapters` table, read together with the memories grouped into each chapter.

The one read here answers the whole of a chapter at once -- its title and summary, and
every memory inside it in order -- because that is the unit a conversation about a video
reasons in: a moment found by search is only meaningful against the section it sits in.

This is the first read of `chapters` that is not part of embedding them, which is why the
table finally has a module of its own. `chapter_embeddings.chapters_for_video` still reads
the table for the embedding pipeline, and stays there: it selects what a vector is built
from, not what a reader is shown.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0005_chapters.sql` and
`migrations/0006_memories.sql` applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from .connection import connection

# One chapter and its memories in a single round trip. The chapter's columns repeat on
# every row, which is the price of not paying for a second query.
#
# Scoped on `video_id` as well as the chapter's own id, so a chapter belonging to another
# video comes back as no rows at all rather than as somebody else's context.
#
# A left join, so a chapter whose memories were detached -- `memories.chapter_id` is
# `on delete set null` -- still answers with itself and one row of null memory columns,
# which is what tells the caller the chapter exists but is empty.
#
# Ordered by `memory_index` rather than `start_seconds`: memories partition the transcript
# end to end with no gaps, so the two orders are the same, but the index is unique per
# video and therefore cannot tie.
CHAPTER_WITH_MEMORIES_SQL = """
select
    c.id as chapter_id,
    c.chapter_index as chapter_index,
    c.title as title,
    c.summary as summary,
    c.start_seconds as chapter_start_seconds,
    c.end_seconds as chapter_end_seconds,
    m.id as memory_id,
    m.summary as memory_summary,
    m.start_seconds as memory_start_seconds,
    m.end_seconds as memory_end_seconds
from public.chapters c
left join public.memories m on m.chapter_id = c.id
where c.id = %s::uuid and c.video_id = %s::uuid
order by m.memory_index
"""


@dataclass(frozen=True)
class StoredChapterMemory:
    """One memory as it appears inside its chapter: what it was about, and when.

    The memory's raw speech is deliberately not carried. A chapter is read for its shape,
    and joining every memory's transcript into one answer would make the longest chapters
    the most expensive to look at.
    """

    memory_id: str
    summary: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class StoredChapter:
    """One chapter, and the memories grouped into it in the order they were spoken.

    `memories` is empty for a chapter whose memories were detached from it. That is a
    coherent state rather than a missing chapter, so it is represented rather than refused.
    """

    chapter_id: str
    chapter_index: int
    title: str
    summary: str
    start_seconds: float
    end_seconds: float
    memories: list[StoredChapterMemory]


class PostgresChapters:
    """The `chapters` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def chapter_with_memories(self, video_id: str, chapter_id: str) -> StoredChapter | None:
        """This video's chapter `chapter_id`, with its memories in order.

        None when the video has no such chapter, which covers both an id that exists
        nowhere and one belonging to a different video. The two are not told apart on
        purpose: a caller that could tell them apart could confirm the existence of another
        video's chapters.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                CHAPTER_WITH_MEMORIES_SQL, (chapter_id, video_id)
            ).fetchall()
        if not rows:
            return None
        return StoredChapter(
            chapter_id=str(rows[0]["chapter_id"]),
            chapter_index=int(rows[0]["chapter_index"]),
            title=rows[0]["title"],
            summary=rows[0]["summary"],
            start_seconds=float(rows[0]["chapter_start_seconds"]),
            end_seconds=float(rows[0]["chapter_end_seconds"]),
            memories=[_to_memory(row) for row in rows if row["memory_id"] is not None],
        )


def _to_memory(row) -> StoredChapterMemory:
    """One joined row's memory half, once it is known to hold a memory at all."""
    return StoredChapterMemory(
        memory_id=str(row["memory_id"]),
        summary=row["memory_summary"],
        start_seconds=float(row["memory_start_seconds"]),
        end_seconds=float(row["memory_end_seconds"]),
    )
