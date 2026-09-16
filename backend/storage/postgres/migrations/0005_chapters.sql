-- The chapters table: a video's broad sections, as an LLM grouped its memories into them.
--
-- Apply 0002_videos.sql first; every row here points at a video. This migration comes
-- before 0006_memories.sql because a memory references the chapter it belongs to.
--
-- A placeholder, in the sense that nothing writes it yet. The stage that produces chapters
-- exists and is tested -- backend/semantic_processing/chapters/ -- but nothing in the
-- request path calls it, so there is no store module for this table either. The schema is
-- here so that the shape is settled and the embedding table in 0007 has something to point
-- at; adding the writer is a later change and needs no migration.
--
-- The columns mirror `VideoChapter` in backend/semantic_processing/chapters/chapter.py.
-- `title` and `summary` are the only two things the model contributes; the times are
-- derived from the memories the chapter covers, which derive them in turn from the
-- transcript segments, so a timestamp in this table was measured rather than invented.

create table if not exists public.chapters (
    id uuid primary key default gen_random_uuid(),

    -- Deleting a video takes its chapters with it, the same as its transcript.
    video_id uuid not null references public.videos (id) on delete cascade,

    -- The chapter's position in the video, counted from zero and with no gaps. Chapters
    -- partition the video end to end, which is what makes the index meaningful on its own.
    chapter_index integer not null,

    title text not null,
    summary text not null,

    start_seconds double precision not null,
    end_seconds double precision not null,

    -- Which model grouped the memories into this chapter, for telling two runs apart
    -- later. Not a switch: a chapter means the same thing whichever model titled it.
    model text,

    created_at timestamptz not null default now(),

    -- One row per position, so a re-run overwrites a video's chapters in place instead of
    -- interleaving the old with the new.
    constraint chapters_video_index_unique unique (video_id, chapter_index),

    constraint chapters_ordered_times check (end_seconds >= start_seconds),
    constraint chapters_index_not_negative check (chapter_index >= 0)
);

comment on table public.chapters is
    'A video''s sections, grouped from its memories; no writer yet.';


create index if not exists chapters_video_index_idx
    on public.chapters (video_id, chapter_index);
