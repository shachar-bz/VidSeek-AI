-- Drops the trigram index on keyframe text (created in 0024) and the `pg_trgm` extension (0023).
--
-- The visual search looked for a query's words in on-screen text with pg_trgm's
-- `word_similarity`. It now looks for each word as a sequence of characters, in Python, over a
-- video's few hundred keyframes (VISUAL_UNDERSTANDING_PLAN.md §5.2), so neither the index nor
-- the extension is used any more. 0023 and 0024 are left as they were because databases that
-- applied them record them as done.
--
-- Once this has run, `pg_trgm` may also be unticked in the server's `azure.extensions`
-- parameter. A new database still runs 0023 first, though, and needs it ticked until then.
drop index if exists public.video_keyframes_ocr_text_trgm_idx;
drop extension if exists pg_trgm;
