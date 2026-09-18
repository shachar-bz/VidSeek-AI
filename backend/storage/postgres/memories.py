"""The `memories` table: a video's transcript as the semantic moments it was divided into.

A plain read of `memories`, unlike `memory_embeddings.memories_for_video`, which reads the
same table but only ever alongside the vectors it exists to write. The two reads here are
what reading a memory *in place* needs: the memory itself, and the run of memories around
it inside one chapter.

`chapter_window` is scoped to a chapter rather than to a video on purpose. `memory_index`
is unique per video and gapless, and chapters partition that sequence end to end, so an
index range plus a chapter id is a window that cannot spill past the chapter's edge -- the
filter is what makes "never cross a chapter boundary" a property of the query rather than
something a caller has to remember to trim afterwards.

`replace` is the writer both of those reads had been waiting for. It takes each memory's
`chapter_id` already resolved, because a chapter's id only exists once the chapter has been
written: `PostgresChapters.replace` runs first and hands its ids back, and the pipeline
stage that owns both decides which memory belongs to which. A memory whose chapter is not
known yet is written with a null `chapter_id`, which is exactly the state memories are in
between the segmentation stage and the grouping stage.

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0006_memories.sql` applied.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .connection import connection

TABLE_NAME = "memories"

# The columns both reads select, in one place because both build the same `StoredMemory`
# out of them and a column added to one read but not the other would be a silent gap.
SELECTED_COLUMNS = (
    "id as memory_id, video_id, chapter_id, memory_index, "
    "text, summary, start_seconds, end_seconds"
)

# One memory written in place, keyed on the position it occupies in the video. Matches
# `memories_video_index_unique` in 0006_memories.sql.
UPSERT_SQL = f"""
insert into public.{TABLE_NAME}
    (video_id, chapter_id, memory_index, text, summary, start_seconds, end_seconds, model)
values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
on conflict (video_id, memory_index) do update set
    chapter_id = excluded.chapter_id,
    text = excluded.text,
    summary = excluded.summary,
    start_seconds = excluded.start_seconds,
    end_seconds = excluded.end_seconds,
    model = excluded.model
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewMemory:
    """One memory as it is handed to `replace`, before the database has given it an id.

    `chapter_id` is the chapter this memory was grouped into, or None while it is ungrouped.
    It is supplied rather than looked up: the id comes from the write that created the
    chapter, and this table is in no position to know which of a video's chapters a memory
    belongs to.
    """

    memory_index: int
    text: str
    summary: str
    start_seconds: float
    end_seconds: float
    chapter_id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class StoredMemory:
    """One memory as it is stored: what was said, when, and where it sits in the video.

    `text` is the speech the memory was built from, joined from its transcript segments and
    otherwise untouched, and `summary` is the one line the segmentation model wrote about
    it. `chapter_id` is None for a memory the chapter-grouping stage has not grouped yet.
    """

    memory_id: str
    video_id: str
    chapter_id: str | None
    memory_index: int
    text: str
    summary: str
    start_seconds: float
    end_seconds: float


class PostgresMemories:
    """The `memories` table, as the rest of the backend sees it."""

    def __init__(self, pool=None):
        self._pool = pool

    def replace(self, video_id: str, memories: Sequence[NewMemory]) -> int:
        """Make this video's stored memories exactly `memories`, and say how many that is.

        Written as an upsert followed by a trim, the same as `PostgresTranscriptSegments`
        and `PostgresComments` and in the same single transaction, so a re-run never leaves
        the video with no memories at all: every position is overwritten in place, and only
        the positions the new segmentation does not reach are removed. The trim relies on
        the segmentation stage's guarantee that `memory_index` runs from zero with no gaps.

        Overwriting in place is also what keeps a memory's id stable across a re-run, which
        matters more here than it does for a transcript segment: `memory_embeddings` points
        at these ids, so a re-segmentation that reused the same boundaries would otherwise
        orphan every vector it had.
        """
        rows = [_to_values(video_id, memory) for memory in memories]
        with connection(self._pool) as open_connection:
            with open_connection.cursor() as cursor:
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                cursor.execute(
                    f"delete from public.{TABLE_NAME} "
                    "where video_id = %s::uuid and memory_index >= %s",
                    (video_id, len(rows)),
                )
        logger.info("Stored %d memories for video %s", len(rows), video_id)
        return len(rows)

    def get(self, video_id: str, memory_id: str) -> StoredMemory | None:
        """This video's memory with that id, or None if the video has no such memory.

        Filtered on `video_id` as well as the primary key, so a memory id belonging to
        another video reads as "not found" rather than handing back a different video's
        transcript. The id must already be a well-formed UUID; the `::uuid` cast raises
        rather than returning None for anything else.
        """
        with connection(self._pool) as open_connection:
            row = open_connection.execute(
                f"select {SELECTED_COLUMNS} from public.{TABLE_NAME} "
                "where id = %s::uuid and video_id = %s::uuid",
                (memory_id, video_id),
            ).fetchone()
        return _to_memory(row) if row else None

    def chapter_window(
        self, chapter_id: str, first_index: int, last_index: int
    ) -> list[StoredMemory]:
        """This chapter's memories whose `memory_index` falls in the inclusive range, in order.

        Returns fewer than the range asks for when the range runs past either end of the
        chapter, which is how a caller learns the window was clipped: there is nothing else
        the chapter could have answered with.
        """
        with connection(self._pool) as open_connection:
            rows = open_connection.execute(
                f"select {SELECTED_COLUMNS} from public.{TABLE_NAME} "
                "where chapter_id = %s::uuid and memory_index between %s and %s "
                "order by memory_index",
                (chapter_id, first_index, last_index),
            ).fetchall()
        return [_to_memory(row) for row in rows]


def _to_values(video_id: str, memory: NewMemory) -> tuple:
    """One memory as the parameters of `UPSERT_SQL`, in its column order."""
    return (
        video_id,
        memory.chapter_id,
        memory.memory_index,
        memory.text,
        memory.summary,
        memory.start_seconds,
        memory.end_seconds,
        memory.model,
    )


def _to_memory(row) -> StoredMemory:
    """One `memories` row as a `StoredMemory`."""
    return StoredMemory(
        memory_id=str(row["memory_id"]),
        video_id=str(row["video_id"]),
        chapter_id=str(row["chapter_id"]) if row["chapter_id"] else None,
        memory_index=int(row["memory_index"]),
        text=row["text"],
        summary=row["summary"],
        start_seconds=float(row["start_seconds"]),
        end_seconds=float(row["end_seconds"]),
    )
