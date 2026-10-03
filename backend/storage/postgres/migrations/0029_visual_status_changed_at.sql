-- When a video's visual status last changed.
--
-- Apply 0022_video_visual_index.sql first.
--
-- A process killed outright -- a crash, a kill -9, a machine losing power -- cannot mark the
-- index it was building as interrupted, so the row keeps saying `indexing`, or `pending` for
-- one still queued, with nothing left to finish it. Every status write sets this column, so
-- an `indexing` or `pending` row that has not changed for far longer than any index takes to
-- build is one whose process is gone, and the job manager claims it on start to build again
-- (`backend/download_pipeline/visual_indexing.py`). Rows that exist already start from now.

alter table public.videos
    add column if not exists visual_status_changed_at timestamptz not null default now();

comment on column public.videos.visual_status_changed_at is
    'When visual_status last changed; an indexing or pending row left long unchanged belongs to a process that died.';
