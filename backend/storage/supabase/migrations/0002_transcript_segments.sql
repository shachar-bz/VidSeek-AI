-- The transcript_segments table: a video's speech, in the timed pieces it was heard in.
--
-- Apply 0001_videos.sql first; every row here points at a video. As with 0001, run this
-- once in Dashboard > SQL Editor or through the Supabase CLI, and re-running it is safe.
--
-- One row per segment rather than one row per transcript, because the timings are the
-- point: a search for a phrase has to come back with the second it was said at, and a
-- transcript stored as one blob of text cannot answer that without being re-parsed by
-- whoever asked. What is true of the transcript as a whole -- its source, its language,
-- how finely it was timed -- is on the video row instead, so it is not repeated on every
-- segment.
--
-- There is no embedding column here. A segment is a mechanical slice of speech, a
-- sentence or two long; the units worth searching semantically are the chapters and
-- memories still to come, and those will carry their own vectors.

create table if not exists public.transcript_segments (
    id uuid primary key default gen_random_uuid(),

    -- Deleting a video takes its transcript with it. A segment describes nothing on its
    -- own, so there is no state in which an orphaned one would be worth keeping.
    video_id uuid not null references public.videos (id) on delete cascade,

    -- The segment's position in the transcript, counted from zero and with no gaps. It is
    -- what the rows are ordered and re-written by; `start_seconds` would nearly always
    -- give the same order, but two segments may share a start and nothing forbids it.
    segment_index integer not null,

    -- Where in the video this was said. Both are measured by whichever service produced
    -- the transcript, never estimated: a transcript with no real timing is rejected
    -- upstream rather than stored with invented numbers.
    start_seconds double precision not null,
    end_seconds double precision not null,

    text text not null,

    created_at timestamptz not null default now(),

    -- One row per position, which is what lets a re-transcription overwrite a video's
    -- segments in place instead of leaving the old ones interleaved with the new.
    constraint transcript_segments_video_index_unique unique (video_id, segment_index),

    constraint transcript_segments_ordered_times check (end_seconds >= start_seconds),
    constraint transcript_segments_index_not_negative check (segment_index >= 0)
);

comment on table public.transcript_segments is
    'One video''s speech as timed segments; the transcript metadata is on videos.';


-- Both things anyone asks of this table are per video: read the whole transcript in
-- order, or find what was being said at some point in the video.
create index if not exists transcript_segments_video_index_idx
    on public.transcript_segments (video_id, segment_index);
create index if not exists transcript_segments_video_time_idx
    on public.transcript_segments (video_id, start_seconds);


-- Closed to the anon and authenticated roles, exactly as `videos` is, and for the same
-- reason. See the note at the end of 0001_videos.sql.
alter table public.transcript_segments enable row level security;
