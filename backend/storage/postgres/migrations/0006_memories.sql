-- The memories table: a video's transcript divided into semantic moments by an LLM.
--
-- Apply 0002_videos.sql and 0005_chapters.sql first; a memory points at both.
--
-- A placeholder in the same sense as chapters: backend/semantic_processing/memories/
-- produces these and is tested, but nothing in the request path calls it, so there is no
-- store module for this table yet.
--
-- The columns mirror `VideoMemory` in backend/semantic_processing/memories/memory.py.
-- `summary` is the only thing the model contributes; `text`, `start_seconds` and
-- `end_seconds` are derived from the transcript segments the memory was built from, so
-- nothing here can drift from what was actually said.

create table if not exists public.memories (
    id uuid primary key default gen_random_uuid(),

    -- Deleting a video takes its memories with it.
    video_id uuid not null references public.videos (id) on delete cascade,

    -- The chapter this memory was grouped into, if it has been grouped at all. Nullable
    -- and `on delete set null` rather than cascading, because the two stages are separate
    -- and run in order: memories are produced first and stand on their own video, and
    -- chapters are built by grouping them afterwards. A memory outliving its chapter is a
    -- coherent state -- it is the state every memory is in before the grouping stage runs
    -- -- whereas a memory deleted because its chapter was regrouped would lose transcript.
    chapter_id uuid references public.chapters (id) on delete set null,

    -- The memory's position in the video, counted from zero and with no gaps. Memories
    -- partition the transcript end to end, the same way chapters partition the memories.
    memory_index integer not null,

    -- The speech this memory covers, joined from its transcript segments and otherwise
    -- untouched, and the one line the model wrote about it.
    text text not null,
    summary text not null,

    start_seconds double precision not null,
    end_seconds double precision not null,

    -- Which model divided the transcript into this memory. See the note in 0005_chapters.sql.
    model text,

    created_at timestamptz not null default now(),

    constraint memories_video_index_unique unique (video_id, memory_index),

    constraint memories_ordered_times check (end_seconds >= start_seconds),
    constraint memories_index_not_negative check (memory_index >= 0)
);

comment on table public.memories is
    'A video''s transcript as semantic moments; no writer yet.';


create index if not exists memories_video_index_idx
    on public.memories (video_id, memory_index);

-- Reading back one chapter's memories is the other question this table answers, and the
-- unique index above is on `video_id` rather than `chapter_id`, so it cannot serve it.
create index if not exists memories_chapter_idx
    on public.memories (chapter_id);
