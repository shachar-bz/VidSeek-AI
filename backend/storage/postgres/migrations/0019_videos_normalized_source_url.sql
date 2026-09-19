-- The deduplication key: one video row per page, however that page was spelled.
--
-- Apply 0002_videos.sql first.
--
-- `source_url` records the URL the extension actually sent, and that is worth keeping
-- exactly as it arrived. It is useless as an identity, though: `youtu.be/X`,
-- `youtube.com/watch?v=X`, the same link with `&t=42`, and the same link again with a
-- `utm_source` on it are four spellings of one video, and each of them downloads,
-- transcribes and segments that video again at full cost. This column is the same URL
-- reduced to what identifies the video, so that the four collapse into one row.
--
-- The reduction is `backend/core/source_urls.py:normalize_source_url`, and that function is
-- the column's definition. Nothing computes this value in SQL: the rules are per-host (a
-- YouTube id can be read off four different path shapes) and a SQL approximation that
-- disagreed with the Python one would be worse than no value at all, because the lookup
-- would miss a row that exists while the index still claimed it was unique.
--
-- Existing rows are left null on purpose. A backfill would have to run that same Python
-- function, so it belongs to the backend rather than to this file; until it runs, an old
-- row simply does not participate in deduplication, which is the state every row was in
-- before this migration. The unique index is partial for exactly that reason -- any number
-- of rows may hold null, and `null = null` is unknown in SQL anyway, so the partial
-- predicate is documentation as much as it is behaviour.
--
-- Consequence worth stating plainly: once a row carries this value, a *second* download of
-- the same page cannot be recorded, because `videos` upserts on
-- (blob_container, blob_name) and a second job uploads under a new blob name (the blob key
-- is prefixed with the job id). That is the intended design -- §11.4 of the website spec
-- has the companion look the video up before it downloads anything and link the existing
-- one instead -- but it means the lookup is not an optimisation that can be skipped. A job
-- that skips it and downloads anyway will fail at the insert rather than quietly making a
-- duplicate.

alter table public.videos
    add column if not exists normalized_source_url text;

comment on column public.videos.normalized_source_url is
    'source_url reduced to what identifies the video, by core/source_urls.py:normalize_source_url.';

-- One video per normalized URL. The lookup a job creation does before downloading anything
-- reads this index, and the uniqueness is what stops two jobs racing to create the same
-- video from both succeeding.
create unique index if not exists videos_normalized_source_url_unique_idx
    on public.videos (normalized_source_url)
    where normalized_source_url is not null;
