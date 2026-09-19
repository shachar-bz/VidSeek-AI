-- The video_insights table: the summary, takeaways and starter questions a finished video
-- carries, so its page says something before anyone asks a question.
--
-- Apply 0002_videos.sql first.
--
-- A table of its own rather than three columns on `videos`, for a reason that is about how
-- `videos` is written rather than about taste. `PostgresVideoRecords.upsert` writes every
-- column of the row from its own dataclass, nulls included, precisely so that a
-- re-download cannot leave a stale value behind. Insight columns living there would be
-- erased by any later upsert of the video, by a writer that has no idea they exist.
--
-- One row per video, keyed on the video itself: these are properties of the shared video,
-- not of a library link, so every account that links the video sees the same ones. That is
-- the same decision `chapters` and `memories` make, and the opposite of the one
-- `user_videos.custom_title` makes.
--
-- Produced once, when processing finishes, by the stage that runs after embedding, and
-- stored -- never generated on page load. The video page reads this table; it does not ask
-- a model anything.

create table if not exists public.video_insights (
    -- The video is the key. There is no separate id: a video has one set of insights or
    -- none, so a generated id would only be a second way to name the row it already has.
    video_id uuid primary key references public.videos (id) on delete cascade,

    summary text not null,

    -- Short lists rather than child tables. Neither is ever queried by its elements, joined
    -- to, or written one at a time -- the generating stage produces the whole set at once
    -- and the page renders the whole set at once -- so the array is the shape the data is
    -- actually used in. `user_videos.tags` is an array for the same reason.
    takeaways text[] not null default '{}',

    -- Starter questions derived from the video's chapters. Each one opens a new conversation
    -- pre-filled with it, so they are stored as the plain text a message would carry and
    -- nothing more.
    suggested_questions text[] not null default '{}',

    -- Which model wrote these, matching `chapters.model` and `memories.model`, so that a
    -- table holding two generations of output can be told apart rather than guessed at.
    model text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.video_insights is
    'A video''s generated summary, key takeaways and suggested questions; shared by every account that links it.';

drop trigger if exists video_insights_set_updated_at on public.video_insights;
create trigger video_insights_set_updated_at
    before update on public.video_insights
    for each row
    execute function public.set_updated_at();
