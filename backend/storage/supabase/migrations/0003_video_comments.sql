-- The video_comments table: a YouTube video's top comments, ranked by like count.
--
-- Apply 0001_videos.sql first; every row here points at a video. As with 0001 and 0002,
-- run this once in Dashboard > SQL Editor or through the Supabase CLI, and re-running it
-- is safe.
--
-- Only YouTube videos ever have rows here -- the YouTube Data API is the only source of
-- comments this project has, and the web pipeline has nothing to write. A video from any
-- other source simply has no rows in this table, the same way it has no `source_video_id`.
--
-- `id` is the comment thread id the YouTube Data API already assigns, so it is the primary
-- key rather than a generated one: it is unique on its own, and reusing it is what lets a
-- re-fetch of the same video's comments overwrite each comment in place.
--
-- There is no embedding column here, and none is planned: unlike the chapters and memories
-- still to come, comments are not meant to be searched semantically, only read back
-- alongside the video they were left on.

create table if not exists public.video_comments (
    id text primary key,

    -- Deleting a video takes its comments with it, the same as transcript_segments.
    video_id uuid not null references public.videos (id) on delete cascade,

    author text not null,
    text text not null,
    like_count integer not null,
    reply_count integer not null,

    -- When the comment was posted on YouTube, not when this row was written.
    published_at timestamptz not null,

    created_at timestamptz not null default now(),

    constraint video_comments_like_count_not_negative check (like_count >= 0),
    constraint video_comments_reply_count_not_negative check (reply_count >= 0)
);

comment on table public.video_comments is
    'A YouTube video''s top comments, ranked by like count; only YouTube videos have rows here.';


-- The one thing anyone asks of this table: a video's comments, best-liked first.
create index if not exists video_comments_video_likes_idx
    on public.video_comments (video_id, like_count desc);


-- Closed to the anon and authenticated roles, exactly as `videos` and `transcript_segments`
-- are, and for the same reason. See the note at the end of 0001_videos.sql.
alter table public.video_comments enable row level security;
