-- The users table: one row per person who has signed up for a VidSeek account.
--
-- Apply 0001_extensions.sql first; `gen_random_uuid()` comes from there. Apply
-- 0002_videos.sql first too; `public.set_updated_at()` is defined there and this table
-- reuses it rather than redefining it.
--
-- 0002_videos.sql explains why videos carries no owner column: until now nothing in this
-- schema knew what a person was, only a Chrome extension installation. This is that
-- concept, arriving as its own migration exactly as promised there. Nothing else points at
-- it yet -- videos, transcript_segments and comments are untouched -- so adding this table
-- changes nothing about how a video is recorded.

create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),

    -- Stored and looked up lower-cased by the backend, but the constraint below is kept
    -- here too so a row written by hand cannot collide silently.
    email text not null,

    -- A bcrypt hash; the password itself is never stored.
    password_hash text not null,

    display_name text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.users is
    'A VidSeek account: the email and password hash a person signs in with.';

create unique index if not exists users_email_unique_idx on public.users (lower(email));

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at
    before update on public.users
    for each row
    execute function public.set_updated_at();
