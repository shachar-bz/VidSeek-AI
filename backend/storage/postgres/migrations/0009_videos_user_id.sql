-- Ties a video to the account that asked for it.
--
-- Apply 0002_videos.sql and 0008_users.sql first; this references both tables.
--
-- Nullable, and `on delete set null` rather than `on delete cascade`: every video row
-- already describes a real file sitting in Blob Storage whether or not anyone owns it, so a
-- video recorded before this column existed, or a signed-out request this deployment never
-- required an account for, is a video with no owner rather than a broken row. Deleting an
-- account orphans the videos it requested instead of deleting them.

alter table public.videos
    add column if not exists user_id uuid references public.users (id) on delete set null;

-- The lookup this column exists for: which videos belong to one account.
create index if not exists videos_user_id_idx on public.videos (user_id);
