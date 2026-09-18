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

Needs AZURE_DATABASE_URL in `backend/.env`, and `migrations/0006_memories.sql` applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from .connection import connection

TABLE_NAME = "memories"

# The columns both reads select, in one place because both build the same `StoredMemory`
# out of them and a column added to one read but not the other would be a silent gap.
SELECTED_COLUMNS = (
    "id as memory_id, video_id, chapter_id, memory_index, "
    "text, summary, start_seconds, end_seconds"
)


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
