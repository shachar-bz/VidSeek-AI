-- The conversations table: one thread of an account talking to the agent about one video.
--
-- Apply 0013_user_videos.sql first; every row here points at a library link rather than at
-- a user and a video separately.
--
-- The foreign key targets `user_videos (user_id, video_id)` rather than `users (id)` and
-- `videos (id)` on their own, so that removing a video from a library takes its
-- conversations with it in the same statement that removes the link -- no second delete,
-- and no way for a conversation to outlive the link it was held under. A conversation
-- about a video the account never linked, or unlinked since, is not a state this schema
-- can represent.
--
-- One user and one video per conversation, matching the website spec's "one video per
-- conversation": a conversation's context is its own message history and nothing else, so
-- there is nothing to gain from letting one span several videos.

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null,
    video_id uuid not null,

    -- Generated from the first exchange once the agent exists; null until then, which is
    -- also what a conversation with no messages yet looks like.
    title text,

    created_at timestamptz not null default now(),

    -- When this conversation was last used, not merely last renamed. `PostgresMessages.add`
    -- bumps this in the same transaction as the message it writes, which is what "newest
    -- first" on the video page actually sorts by.
    updated_at timestamptz not null default now(),

    constraint conversations_user_video_fkey
        foreign key (user_id, video_id) references public.user_videos (user_id, video_id)
        on delete cascade
);

comment on table public.conversations is
    'One user''s conversation thread with the agent about one video.';

-- The one listing the video page needs: this user's conversations about this video, most
-- recently used first.
create index if not exists conversations_user_video_idx
    on public.conversations (user_id, video_id, updated_at desc);

drop trigger if exists conversations_set_updated_at on public.conversations;
create trigger conversations_set_updated_at
    before update on public.conversations
    for each row
    execute function public.set_updated_at();
