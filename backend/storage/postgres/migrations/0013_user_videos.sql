-- The user_videos table: one row per account that has linked one video into their library.
--
-- Apply 0008_users.sql and 0002_videos.sql first; every row here points at both.
--
-- Replaces the single `videos.user_id` column 0009 added. That column made a video belong
-- to at most one account, which stopped being true the moment a second account could
-- download something another account had already downloaded: the video is one row either
-- way, so ownership has to live beside the video, not on it. This is that link, and it
-- carries what is genuinely per-account rather than per-video: the title a user gave it,
-- the tags they filed it under, and when they added it. Two rows can point at the same
-- `video_id` with none of that in common.
--
-- Keyed on `(user_id, video_id)` rather than a generated id: a user either has a video in
-- their library or does not, so there is never a second link to tell apart from the first,
-- and the pair is what every write and every read already knows.

create table if not exists public.user_videos (
    user_id uuid not null references public.users (id) on delete cascade,
    video_id uuid not null references public.videos (id) on delete cascade,

    -- This user's own name for the video, if they renamed it. Null means the video's own
    -- `title` is shown, which is why nothing here duplicates it.
    custom_title text,

    -- Free text, created on first use rather than drawn from a fixed list -- see
    -- 0002_videos.sql's reasoning for `source` being text rather than an enum for the same
    -- kind of column that should not need a migration to grow.
    tags text[] not null default '{}',

    added_at timestamptz not null default now(),

    primary key (user_id, video_id)
);

comment on table public.user_videos is
    'A library link: one account''s title, tags and add time for one video.';

-- The other direction from the primary key: which accounts have linked one video, which a
-- re-download's dedup check needs before it can decide whether to add a link or do nothing.
create index if not exists user_videos_video_id_idx on public.user_videos (video_id);

-- Supports "filter by tag" (§3.3 of the website spec) as a containment test against the
-- array rather than a sequential scan of every user's library.
create index if not exists user_videos_tags_gin_idx on public.user_videos using gin (tags);


-- The migration this table replaces. Existing single-owner rows become link rows so that
-- an account that already had a video does not lose it; `videos.created_at` stands in for
-- `added_at` because that is the only notion of "when" a pre-library row has. A video with
-- no owner (`user_id is null`) simply gets no link, the same way it had no owner before.
insert into public.user_videos (user_id, video_id, added_at)
select user_id, id, created_at
from public.videos
where user_id is not null
on conflict (user_id, video_id) do nothing;

drop index if exists public.videos_user_id_idx;
alter table public.videos drop column if exists user_id;
