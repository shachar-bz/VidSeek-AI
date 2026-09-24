-- The visual index: what a video shows, as vectors, segments and keyframe timestamps, plus the
-- captions the visual sub-agent writes whenever it has to look at pixels.
--
-- Apply 0001_extensions.sql (which creates `vector`) and 0002_videos.sql first.
--
-- VISUAL_UNDERSTANDING_PLAN.md is the design. The index is built in the background from the
-- local copy of a video once it is stored (`backend/download_pipeline/visual_indexing.py`),
-- separately from the transcript stages, which is why its progress lives in columns of its own
-- rather than in `video_jobs`: the job is done, and reports done, long before the index is.
--
-- No images are stored anywhere. Frames are decoded, embedded and hashed in memory and then
-- discarded; when pixels are needed at query time they are extracted again from the video in
-- Blob Storage at the recorded timestamp.
--
-- On-screen text (OCR) is not part of this migration. The OCR engine is still to be chosen,
-- and the columns and the trigram index that hold its output arrive with it.


-- --- videos: how far the visual index is ---------------------------------------------------

-- `visual_status` moves pending -> indexing -> ready | failed | skipped. New rows start at
-- pending because the pipeline hands every stored video to the visual executor. These
-- columns are deliberately absent from `VideoRecord`: `PostgresVideoRecords.upsert` writes
-- every column that dataclass names, nulls included, and a re-recorded video would
-- otherwise have its index status erased by a writer that knows nothing about it
-- (0020_video_insights.sql makes the same argument for a table of its own).
alter table public.videos
    add column if not exists visual_status text not null default 'pending',
    -- Why the index failed or was skipped, as a short code; null otherwise.
    add column if not exists visual_error text,
    -- The models and sampling rate the stored index was built with, e.g.
    -- "siglip2-base-patch16-256@0.5fps". Vectors from two models cannot be compared, so a
    -- search refuses to read an index whose version is not the one the backend now builds,
    -- and this column is what lists the videos that need re-indexing after a model change.
    add column if not exists visual_index_version text;

alter table public.videos drop constraint if exists videos_visual_status_known;
alter table public.videos add constraint videos_visual_status_known
    check (visual_status in ('pending', 'indexing', 'ready', 'failed', 'skipped'));

-- Every row that exists when this runs was ingested before visual indexing did, and nothing
-- will index it: backfilling is out of scope for v1. Saying `skipped` rather than leaving the
-- default is what keeps `pending` meaning "a visual task is queued for this video".
update public.videos
    set visual_status = 'skipped', visual_error = 'ingested_before_visual_indexing'
    where visual_status = 'pending';


-- --- video_frame_embeddings: one vector per sampled frame ------------------------------------

-- ~1,800 rows per hour of video (one frame every 2 s). The primary key is also the index
-- every read uses: a query is always about one video and scores every one of its frames,
-- because a hit is judged against that video's own score distribution
-- (`backend/services/visual_search/`). An ANN index would answer "the nearest few frames of
-- every video" and is exactly the wrong shape, so there is none.
create table if not exists public.video_frame_embeddings (
    video_id uuid not null references public.videos (id) on delete cascade,
    time_seconds double precision not null,

    -- SigLIP 2 base image embedding, L2-normalized so `<=>` is plain cosine distance.
    embedding vector(768) not null,

    constraint video_frame_embeddings_pkey primary key (video_id, time_seconds),
    constraint video_frame_embeddings_time_not_negative check (time_seconds >= 0)
);

comment on table public.video_frame_embeddings is
    'One SigLIP 2 image embedding per sampled frame (0.5 fps); scored exhaustively per video.';


-- --- video_visual_segments: the sub-agent's map ------------------------------------------------

-- A segment is a stretch of the video whose content stays the same, cut where the image
-- embedding or the perceptual hash of the sampled frames changes and stays changed. Segments
-- partition the video end to end.
--
-- There is no `chapter_id`. Visual indexing runs in parallel with the transcript stages, so the
-- chapters usually do not exist yet when these rows are written, and a chapter's times can
-- change when the transcript is segmented again. The chapter a segment falls in is read by
-- time instead (`backend/storage/postgres/visual_index.py`), which is never stale.
create table if not exists public.video_visual_segments (
    id uuid primary key default gen_random_uuid(),
    video_id uuid not null references public.videos (id) on delete cascade,

    -- Position in the video, from zero with no gaps.
    segment_index integer not null,

    start_seconds double precision not null,
    end_seconds double precision not null,

    -- What opened this segment: `video_start` for the first one, `scene_change` when the
    -- image embedding moved (a cut, a new view), `text_change` when only the perceptual hash
    -- did (a new slide, new writing on a board). A sequence of frames is never taken across a
    -- `scene_change` boundary.
    boundary_kind text not null,

    constraint video_visual_segments_video_index_unique unique (video_id, segment_index),
    constraint video_visual_segments_ordered_times check (end_seconds >= start_seconds),
    constraint video_visual_segments_index_not_negative check (segment_index >= 0),
    constraint video_visual_segments_boundary_kind_known
        check (boundary_kind in ('video_start', 'scene_change', 'text_change'))
);

comment on table public.video_visual_segments is
    'A video divided where its picture changes; the visual sub-agent''s map of the video.';

create index if not exists video_visual_segments_video_start_idx
    on public.video_visual_segments (video_id, start_seconds);


-- --- video_keyframes: the frames worth reading again -----------------------------------------

-- One keyframe per segment (its first stable frame) plus one every ~60 s inside a long,
-- static segment, such as a board being written on slowly: ~100-300 per hour. Only the
-- timestamp is kept; the frame is extracted again from the video whenever it is needed.
-- `video_id` repeats the segment's so one video's keyframes are read without a join.
create table if not exists public.video_keyframes (
    id uuid primary key default gen_random_uuid(),
    video_id uuid not null references public.videos (id) on delete cascade,
    segment_id uuid not null references public.video_visual_segments (id) on delete cascade,
    time_seconds double precision not null,

    constraint video_keyframes_video_time_unique unique (video_id, time_seconds),
    constraint video_keyframes_time_not_negative check (time_seconds >= 0)
);

comment on table public.video_keyframes is
    'Timestamps of the frames that stand for each visual segment; no pixels are stored.';

create index if not exists video_keyframes_segment_idx on public.video_keyframes (segment_id);


-- --- video_frame_captions: what the sub-agent saw, paid for once -------------------------------

-- Whenever the visual sub-agent looks at a frame or a grid of frames, it writes a short,
-- general caption of what is visible, and the caption is kept so the next question about that
-- part of the video reads text instead of paying for the pixels again. Empty at ingestion; it
-- grows with use.
--
-- Keyed by time rather than by segment: a caption was paid for with a VLM call and describes a
-- moment of the video, which stays true when the visual index is rebuilt with other models and
-- its segments are replaced. The segment a caption falls in is read by time, like the chapter.
create table if not exists public.video_frame_captions (
    id uuid primary key default gen_random_uuid(),
    video_id uuid not null references public.videos (id) on delete cascade,

    time_seconds double precision not null,
    -- Set for a caption of a sequence grid, which describes a window rather than one frame.
    end_seconds double precision,

    caption text not null,

    -- multilingual-e5-small, L2-normalized, so a Hebrew or an English question finds it.
    caption_embedding vector(384) not null,

    -- The VLM that wrote the caption, so captions from a model that proved unreliable can be
    -- found and dropped.
    model text not null,

    created_at timestamptz not null default now(),

    constraint video_frame_captions_time_not_negative check (time_seconds >= 0),
    constraint video_frame_captions_ordered_times
        check (end_seconds is null or end_seconds >= time_seconds)
);

comment on table public.video_frame_captions is
    'General captions the visual sub-agent wrote for frames it viewed; grows with use.';

create index if not exists video_frame_captions_video_time_idx
    on public.video_frame_captions (video_id, time_seconds);
