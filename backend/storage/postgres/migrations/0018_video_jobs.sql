-- The video_jobs table: what the companion is doing to one video, where anything can read it.
--
-- Apply 0008_users.sql and 0002_videos.sql first; a row points at the account that started
-- the job and, once stage two has run, at the video it produced.
--
-- `JobManager` keeps jobs in an in-memory dict on a single worker. Three things follow from
-- that, and this table is what fixes all three: a hosted website cannot see a job at all, a
-- restart loses every job in flight, and the dict only ever grows because nothing evicts a
-- finished one (OPEN_TASKS.md #3). The library page's live processing rows read this table.
--
-- The row is written by the companion as it works and read by everyone else. It is
-- deliberately a mirror of `VideoJobResponse` rather than a second vocabulary: `status`,
-- `phase`, `progress`, `message` and `error_code` hold exactly what that model carries, so
-- that the website and the extension describe the same job the same way and neither has to
-- translate. The secret-bearing halves of a job -- cookies, headers, candidate URLs -- stay
-- in memory and are never written here, for the same reason `VideoJobResponse` omits them.
--
-- `id` is text rather than uuid because the companion generates it as `uuid4().hex`, and
-- `videos.job_id` already records it as text. Keeping the two spellings identical is what
-- lets a video be traced back to the job that produced it without a cast.

create table if not exists public.video_jobs (
    id text primary key,

    -- The account that started the job. Nullable because `JobManager.create` accepts a job
    -- with no account -- the API route requires one, but the manager does not -- and a job
    -- nobody owns is still worth recording. It is simply invisible to every library page,
    -- which is the honest consequence rather than a gap.
    user_id uuid references public.users (id) on delete cascade,

    -- The video this job produced, once stage two has written its row. Null for the whole
    -- of the download and transcription phases, which is precisely the window in which the
    -- library has nothing but this row to show. `on delete set null` rather than cascade:
    -- a video removed from the database does not make the job that produced it untrue.
    video_id uuid references public.videos (id) on delete set null,

    -- What the library shows while there is no video row yet: the page the job is working
    -- on and what the tab was called. Copied from `CreateVideoJobRequest` rather than read
    -- through `video_id`, because for most of a job's life there is nothing to read.
    page_url text not null,
    page_title text not null,

    -- `JobStatus` and `JobPhase` from backend/schemas/video_jobs.py, stored as their string
    -- values. Free text for the reason 0002_videos.sql gives for `source`: adding a phase
    -- should not mean shipping a migration before a job can report it.
    status text not null,
    phase text not null,
    progress double precision not null default 0,
    message text not null default '',

    -- The companion's own name for how the video was obtained, matching `videos.source`.
    acquisition_mode text,

    -- Set only on a job that failed or finished with caveats; the same codes
    -- `VideoJobResponse.error_code` carries.
    error_code text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint video_jobs_progress_fraction check (progress >= 0 and progress <= 1)
);

comment on table public.video_jobs is
    'One companion job''s live status, phase and progress, readable by anything sharing this database.';

-- The library's own read: this account's jobs, newest first. Every processing row on the
-- library page comes from here.
create index if not exists video_jobs_user_created_idx
    on public.video_jobs (user_id, created_at desc);

-- The other direction: which job produced one video, for a library row that has both.
create index if not exists video_jobs_video_id_idx on public.video_jobs (video_id);

drop trigger if exists video_jobs_set_updated_at on public.video_jobs;
create trigger video_jobs_set_updated_at
    before update on public.video_jobs
    for each row
    execute function public.set_updated_at();
