-- The videos table: one row per video whose file has been stored in Cloudflare R2.
--
-- Run this once against the Supabase project, in Dashboard > SQL Editor or through the
-- Supabase CLI. Nothing in the backend creates or alters tables: a running service that
-- can rewrite its own schema is a larger risk than a manual step taken once.
--
-- Re-running it is safe. Every statement is written to be idempotent, so this file can be
-- applied again after an edit without dropping what is already in the table.

-- pgvector, for the embedding columns the chapters and memories tables will carry. It is
-- enabled here rather than in that later migration because enabling an extension is a
-- one-off project-level step, and having it in place costs nothing until something uses
-- it. No column in this migration is a vector.
create extension if not exists vector;


create table if not exists public.videos (
    id uuid primary key default gen_random_uuid(),

    -- Which pipeline produced the video, stored as the companion's own acquisition mode:
    -- "youtube_pipeline", "companion_download", "browser_download" or "captured_request".
    -- Deliberately free text rather than an enum, so that adding a pipeline does not mean
    -- shipping a migration before it can record anything.
    source text not null,

    -- The page the video was taken from, and the source's own id for it where there is
    -- one (a YouTube video id). Both are kept: the same video is reachable under several
    -- URLs, and not every source has an id.
    source_url text not null,
    source_video_id text,

    title text not null,
    duration_seconds double precision,

    -- What is true of the video's transcript as a whole, with the transcript itself in
    -- `transcript_segments` (0002). `transcript_source` names the service the text came
    -- from ("youtube_captions", "elevenlabs", "captions", ...); `transcript_timing_fidelity`
    -- is "word" or "caption" and says how finely that service measured the timings, which
    -- is what tells a later reader how much a segment boundary is worth. All three are
    -- null until a job produces a transcript.
    transcript_source text,
    transcript_language text,
    transcript_timing_fidelity text,

    -- Where the file itself is. The bucket is recorded beside the key because a key on
    -- its own does not say which bucket holds it, and this project has already changed
    -- its bucket layout once.
    r2_bucket text not null,
    r2_object_key text not null,
    file_size_bytes bigint,
    content_type text,

    -- The companion job that produced this row, so a row can be traced back to its logs.
    -- Not a foreign key: jobs live in memory on one machine and are gone by the next run.
    job_id text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    -- One row per stored object. This is what lets a re-run of the same job update its
    -- row instead of adding a second one, since re-uploading writes the same R2 key.
    constraint videos_bucket_object_key_unique unique (r2_bucket, r2_object_key)
);

comment on table public.videos is
    'Video metadata; the file itself lives in Cloudflare R2 under r2_bucket/r2_object_key.';


-- Looking a video up by the page it came from is how the companion answers "have we
-- already downloaded this?", and the newest-first listing is what a browse view reads.
create index if not exists videos_source_url_idx on public.videos (source_url);
create index if not exists videos_created_at_idx on public.videos (created_at desc);


-- `updated_at` is maintained by the database rather than by each writer, so a row edited
-- from the SQL editor carries the same timestamp discipline as one written by the backend.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists videos_set_updated_at on public.videos;
create trigger videos_set_updated_at
    before update on public.videos
    for each row
    execute function public.set_updated_at();


-- Row level security is on with no policies attached, which denies the anon and
-- authenticated roles everything. The service role bypasses RLS, so the backend reaches
-- the table with SUPABASE_SERVICE_ROLE_KEY and nothing holding only the anon key can read
-- or write it. That matters because the anon key ships in any client that has it.
alter table public.videos enable row level security;

-- If you want to work against this table with the anon key alone -- a local experiment,
-- or the Supabase dashboard's API explorer -- uncomment the block below. It opens the
-- table to anyone who has the anon key, which for a project that ever exposes that key to
-- a browser means the public. Prefer the service role key in the backend instead.
--
-- create policy videos_anon_read on public.videos for select to anon using (true);
-- create policy videos_anon_write on public.videos for all to anon using (true) with check (true);
