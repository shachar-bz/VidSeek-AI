-- Corrects what the chapters and memories tables say about themselves, now that something
-- writes them.
--
-- Apply after 0005_chapters.sql and 0006_memories.sql. Both were created as placeholders:
-- the stages that produce chapters and memories existed and were tested, but nothing in the
-- request path called them, so both tables carried a comment saying they had no writer. That
-- is no longer true -- backend/download_pipeline/segmentation.py runs both stages and writes
-- what they produce through PostgresChapters.replace and PostgresMemories.replace -- and a
-- table that describes itself wrongly is worse than one that does not describe itself at all.
--
-- Comments only. No column, constraint or index changes: the shapes 0005 and 0006 settled
-- turned out to be the shapes the writer needed, which is what they were settled for.

comment on table public.chapters is
    'A video''s sections, grouped from its memories by the download pipeline''s '
    'segmentation stage.';

comment on table public.memories is
    'A video''s transcript as semantic moments, divided by the download pipeline''s '
    'segmentation stage.';
