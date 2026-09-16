-- The comments table: a YouTube video's top comments, ranked by like count.
--
-- Apply 0002_videos.sql first; every row here points at a video.
--
-- Only YouTube videos ever have rows here -- the YouTube Data API is the only source of
-- comments this project has, and the web pipeline has nothing to write. A video from any
-- other source simply has no rows in this table, the same way it has no `source_video_id`.
--
-- `id` is the comment thread id the YouTube Data API already assigns, so it is the primary
-- key rather than a generated one: it is unique on its own, and reusing it is what lets a
-- re-fetch of the same video's comments overwrite each comment in place.
--
-- There is no embedding column here, and none is planned: unlike the memories and chapters
-- in 0005 and 0006, comments are not meant to be searched semantically, only read back
-- alongside the video they were left on.

create table if not exists public.comments (
    id text primary key,

    -- Deleting a video takes its comments with it, the same as transcript_segments.
    video_id uuid not null references public.videos (id) on delete cascade,

    author text not null,
    text text not null,

    -- How many likes the comment carries, and how many replies hang off it. `like_count`
    -- is not decoration: it is the order YouTube's own "Top comments" is in, and the order
    -- this table is read back in.
    like_count integer not null,
    reply_count integer not null,

    -- When the comment was posted on YouTube, not when this row was written.
    published_at timestamptz not null,

    created_at timestamptz not null default now(),

    constraint comments_like_count_not_negative check (like_count >= 0),
    constraint comments_reply_count_not_negative check (reply_count >= 0)
);

comment on table public.comments is
    'A YouTube video''s top comments, ranked by like count; only YouTube videos have rows here.';


-- The one thing anyone asks of this table: a video's comments, best-liked first.
create index if not exists comments_video_likes_idx
    on public.comments (video_id, like_count desc);
