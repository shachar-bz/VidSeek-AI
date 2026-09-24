-- The on-screen text of each keyframe: slides, boards, code, text over footage, read by OCR.
--
-- Apply 0022_video_visual_index.sql (which creates `video_keyframes`) and
-- 0023_trigram_extension.sql (which creates `pg_trgm`) first.
--
-- VISUAL_UNDERSTANDING_PLAN.md §3.2 step 5 is the design. Text is read after the rest of the
-- visual index is stored, from the local copy of the video at full resolution
-- (`backend/download_pipeline/visual_indexing.py`), and written onto the keyframe rows that
-- index created. Nothing new is stored as an image: only the text and what it means.
--
-- `ocr_engine` is what separates the three states a keyframe can be in:
--   * null                      -- not read: OCR is not set up on the machine that indexed the
--                                  video, it failed, or it has not reached this keyframe yet;
--   * set, `ocr_text` null      -- read, and it shows no text worth keeping;
--   * set, `ocr_text` set       -- read, and this is its text.
-- Recording the engine per keyframe rather than in `videos.visual_index_version` is on purpose:
-- the frame vectors do not depend on it, so turning OCR on or off, or changing the engine,
-- must not make a whole index unsearchable.

alter table public.video_keyframes
    -- The blocks the engine read, in reading order, one per line; tags and markup removed.
    add column if not exists ocr_text text,
    -- By script: `he`, `en` (Latin), `mixed`, or `other`; null for text with no letters.
    add column if not exists ocr_language text,
    -- The engine's confidence in the text, 0-1, the blocks' mean weighted by length.
    add column if not exists ocr_confidence real,
    -- multilingual-e5-small, L2-normalized, so a Hebrew or an English question finds it.
    add column if not exists ocr_embedding vector(384),
    -- The engine that read this keyframe, e.g. `surya-ocr-2`.
    add column if not exists ocr_engine text;

alter table public.video_keyframes drop constraint if exists video_keyframes_ocr_language_known;
alter table public.video_keyframes add constraint video_keyframes_ocr_language_known
    check (ocr_language is null or ocr_language in ('he', 'en', 'mixed', 'other'));

alter table public.video_keyframes drop constraint if exists video_keyframes_ocr_text_read_by_an_engine;
alter table public.video_keyframes add constraint video_keyframes_ocr_text_read_by_an_engine
    check (ocr_text is null or ocr_engine is not null);

-- Exact words: "where does the slide say Kubernetes". Searches of one video read every one of
-- its few hundred keyframes and do not need it; it is what makes the same question across a
-- whole library cheap.
create index if not exists video_keyframes_ocr_text_trgm_idx
    on public.video_keyframes using gin (ocr_text gin_trgm_ops);

-- No ANN index on `ocr_embedding`, for the reason `video_frame_captions` has none: a query is
-- about one video, whose keyframes are few enough to score them all.
