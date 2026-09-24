-- Drops `video_frame_captions` (created in 0022).
--
-- The table was to hold the captions the visual sub-agent writes for frames it looks at, so a
-- later question could read text instead of paying for the pixels again. That mechanism is
-- removed until the sub-agent exists; nothing ever wrote to the table, so no data is lost.
-- 0022 is left as it was because databases that applied it record it as done.
drop table if exists public.video_frame_captions;
