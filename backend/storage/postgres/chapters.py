"""The `chapters` table: a chapter's contents, and where it sits among the other chapters.

`chapter_with_memories` answers the whole of a chapter at once -- its title and summary,
and every memory inside it in order -- because that is the unit a conversation about a
video reasons in: a moment found by search is only meaningful against the section it sits
in. `with_neighbours` answers the other question, asked by a caller that has read to the
edge of a chapter and needs somewhere to go next: what is this chapter called, and what
lies either side of it. `video_outline` answers neither: it steps back and names every
chapter of a video at once, for a caller that does not yet know which section it wants.

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


# Every chapter of a video, named and timed but without its memories. This is the whole of
# a video's structure in one read, which is why nothing is joined to it: a caller asking how
# the video is organized is asking about the sections, and pulling in their memories would
# make the answer grow with the length of the video rather than with the number of chapters.
#
# Ordered by `chapter_index` rather than `start_seconds`, for the same reason
# `CHAPTER_WITH_MEMORIES_SQL` orders memories by their index: 0005_chapters.sql counts the
# index from zero with no gaps, so the two orders agree, but the index is unique per video
# and therefore cannot tie.
#
# No limit. A video has as many chapters as it has sections, and half a video's structure
# is not a structure.
VIDEO_OUTLINE_SQL = """
select
    id as chapter_id,
    chapter_index,
    title,
    summary,
    start_seconds,
    end_seconds
from public.chapters
where video_id = %s::uuid
order by chapter_index
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


# A chapter and the two chapters either side of it, in a single round trip. The neighbours
# are found at `chapter_index` one either side: 0005_chapters.sql counts the index from
# zero with no gaps, so adjacency is arithmetic rather than a search through the video's
# times.
#
# Scoped on `video_id` as well as the chapter's own id, for the same reason
# `CHAPTER_WITH_MEMORIES_SQL` is.
#
# Left joins, so the first and last chapters of a video still answer with themselves. A
# null neighbour there is the video's own edge rather than a missing row.
#
# Each side's columns are prefixed, because all three chapters are the same four columns
# and would otherwise collide in one row.
CHAPTER_WITH_NEIGHBOURS_SQL = """
select
    chapter.id as chapter_id,
    chapter.chapter_index as chapter_index,
    chapter.title as title,
    chapter.summary as summary,
    preceding.id as preceding_id,
    preceding.chapter_index as preceding_index,
    preceding.title as preceding_title,
    preceding.summary as preceding_summary,
    following.id as following_id,
    following.chapter_index as following_index,
    following.title as following_title,
    following.summary as following_summary
from public.chapters chapter
left join public.chapters preceding
    on preceding.video_id = chapter.video_id
    and preceding.chapter_index = chapter.chapter_index - 1
left join public.chapters following
    on following.video_id = chapter.video_id
    and following.chapter_index = chapter.chapter_index + 1
where chapter.id = %s::uuid and chapter.video_id = %s::uuid
"""


@dataclass(frozen=True)
class ChapterHeading:
    """A chapter reduced to what names it: its position, its title and its one-line summary.

    Not `StoredChapter`, which carries the chapter's memories and timing. A caller pointing
    at a neighbouring chapter is offering the model somewhere to read next, and reading it
    is the next call's job; naming three chapters should not cost three chapters' contents.
    """

    chapter_id: str
    chapter_index: int
    title: str
    summary: str


@dataclass(frozen=True)
class StoredChapterOutline:
    """One chapter of a video as it appears in the video's outline: named, placed and timed.

    `ChapterHeading` is the same chapter without its times, and stays that way: a caller
    naming a neighbour is offering somewhere to read next, where a timestamp says nothing,
    while a caller reading the outline is deciding which part of the video to look at, where
    the timing is half of what the decision is made on.

    The chapter's memories are not carried, which is the whole point of the read.
    """

    chapter_id: str
    chapter_index: int
    title: str
    summary: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ChapterWithNeighbours:
    """A chapter, named, and the chapters either side of it.

    `preceding` is None at the video's first chapter and `following` at its last: the
    section boundary is the video's own edge, and there is nowhere further to read.
    """

    chapter: ChapterHeading
    preceding: ChapterHeading | None
    following: ChapterHeading | None


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

    def with_neighbours(self, video_id: str, chapter_id: str) -> ChapterWithNeighbours | None:
        """This video's chapter `chapter_id`, named, and the chapters either side of it.

        None when the video has no such chapter, for the same reason and with the same
        discretion as `chapter_with_memories`.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                CHAPTER_WITH_NEIGHBOURS_SQL, (chapter_id, video_id)
            ).fetchone()
        if row is None:
            return None
        return ChapterWithNeighbours(
            chapter=ChapterHeading(
                chapter_id=str(row["chapter_id"]),
                chapter_index=int(row["chapter_index"]),
                title=row["title"],
                summary=row["summary"],
            ),
            preceding=_to_heading(row, "preceding"),
            following=_to_heading(row, "following"),
        )

    def video_outline(self, video_id: str) -> list[StoredChapterOutline]:
        """Every chapter of this video, earliest first.

        Empty for a video that has not been divided into chapters, and empty for a video id
        that describes nothing at all. The two are not told apart here: this reads the
        `chapters` table, which has nothing to say about whether a video exists, and a
        caller that needs to tell them apart asks `PostgresVideoRecords.exists`.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(VIDEO_OUTLINE_SQL, (video_id,)).fetchall()
        return [_to_outline(row) for row in rows]



def _to_memory(row) -> StoredChapterMemory:
    """One joined row's memory half, once it is known to hold a memory at all."""
    return StoredChapterMemory(
        memory_id=str(row["memory_id"]),
        summary=row["memory_summary"],
        start_seconds=float(row["memory_start_seconds"]),
        end_seconds=float(row["memory_end_seconds"]),
    )


def _to_outline(row) -> StoredChapterOutline:
    """One row of the outline read, as the chapter it describes."""
    return StoredChapterOutline(
        chapter_id=str(row["chapter_id"]),
        chapter_index=int(row["chapter_index"]),
        title=row["title"],
        summary=row["summary"],
        start_seconds=float(row["start_seconds"]),
        end_seconds=float(row["end_seconds"]),
    )


def _to_heading(row, prefix: str) -> ChapterHeading | None:
    """One side's chapter out of a `with_neighbours` row, or None where the video ends."""
    if not row[f"{prefix}_id"]:
        return None
    return ChapterHeading(
        chapter_id=str(row[f"{prefix}_id"]),
        chapter_index=int(row[f"{prefix}_index"]),
        title=row[f"{prefix}_title"],
        summary=row[f"{prefix}_summary"],
    )
