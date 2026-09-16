-- The videos table: one row per video whose file has been stored in Azure Blob Storage.
--
-- Apply 0001_extensions.sql first; `gen_random_uuid()` comes from there.
--
-- This is the root every other table hangs off. Blob Storage holds the bytes and nothing
-- else -- a blob's name says nothing about which page the video came from, what it is
-- called, or whether it was transcribed -- so this is the other half, keyed on the blob it
-- describes, so that a blob found in the container can be turned back into a video and a
-- page URL can be turned into the blob that holds it.
--
-- There is no owner column. The product has no user concept: a request is authorized by a
-- short-lived token bound to a Chrome extension id, which identifies an installation
-- rather than a person, and a `user_id` filled in from one would be a guess written into
-- the table. When real accounts exist, they arrive as their own migration.

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
    -- `transcript_segments` (0003). `transcript_source` names the service the text came
    -- from ("youtube_captions", "elevenlabs", "captions", ...); `transcript_timing_fidelity`
    -- is "word" or "caption" and says how finely that service measured the timings, which
    -- is what tells a later reader how much a segment boundary is worth. `transcript_language`
    -- is the language the speech was in -- it belongs to the whole transcript, not to any
    -- one segment, which is why no segment row repeats it. All three are null until a job
    -- produces a transcript.
    transcript_source text,
    transcript_language text,
    transcript_timing_fidelity text,

    -- Where the file itself is. The container is recorded beside the blob name because a
    -- name on its own does not say which container holds it, and this project has already
    -- changed its storage layout once.
    blob_container text not null,
    blob_name text not null,
    file_size_bytes bigint,
    content_type text,

    -- The companion job that produced this row, so a row can be traced back to its logs.
    -- Not a foreign key: jobs live in memory on one machine and are gone by the next run.
    job_id text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    -- One row per stored blob. This is what lets a re-run of the same job update its row
    -- instead of adding a second one, since re-uploading writes the same blob name.
    constraint videos_container_blob_name_unique unique (blob_container, blob_name)
);

comment on table public.videos is
    'Video metadata; the file itself lives in Azure Blob Storage at blob_container/blob_name.';


-- Looking a video up by the page it came from is how the companion answers "have we
-- already downloaded this?", and the newest-first listing is what a browse view reads.
create index if not exists videos_source_url_idx on public.videos (source_url);
create index if not exists videos_created_at_idx on public.videos (created_at desc);


-- `updated_at` is maintained by the database rather than by each writer, so a row edited
-- by hand carries the same timestamp discipline as one written by the backend.
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


-- No row level security anywhere in this schema. The hosted row API this database replaces
-- needed it, because there the tables were one HTTP request away from any browser holding
-- the public key. Here there is no such key and no such request: the database is reached
-- over one connection string that lives in backend/.env, is read only by
-- backend/core/config.py, and never leaves the backend. Adding policies would guard against
-- a role that does not exist.
