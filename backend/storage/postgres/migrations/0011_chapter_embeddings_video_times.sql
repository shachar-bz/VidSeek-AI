-- Fixes chapter_embeddings now that something actually produces embeddings:
-- backend/services/embeddings/chapter_embedding embeds a chapter's title and summary with
-- the shared all-MiniLM-L6-v2 model (backend/services/embeddings/model.py), a
-- 384-dimensional model.
--
-- Apply after 0005_chapters.sql and 0007_embeddings.sql.
--
-- video_id, start_seconds and end_seconds are denormalized onto this table from
-- chapters.video_id/start_seconds/end_seconds, so a similarity search can filter by video or
-- read a match's timing without joining through chapters for every row. All three are not
-- null, mirroring the columns they are copied from -- every chapter belongs to a video and
-- has a measured start and end.
--
-- The embedding column's dimension was left unfixed in 0007 because no model had been
-- chosen yet. It is fixed here at 384. No ANN index (hnsw or otherwise) is added: retrieval
-- and search strategy belong to the dedicated semantic search layer, not this migration.

alter table public.chapter_embeddings
    add column if not exists video_id uuid references public.videos (id) on delete cascade,
    add column if not exists start_seconds double precision,
    add column if not exists end_seconds double precision;

update public.chapter_embeddings ce
    set video_id = c.video_id,
        start_seconds = c.start_seconds,
        end_seconds = c.end_seconds
    from public.chapters c
    where ce.chapter_id = c.id and ce.video_id is null;

alter table public.chapter_embeddings
    alter column video_id set not null,
    alter column start_seconds set not null,
    alter column end_seconds set not null;

alter table public.chapter_embeddings
    add constraint chapter_embeddings_ordered_times check (end_seconds >= start_seconds);

alter table public.chapter_embeddings alter column embedding type vector(384);

create index if not exists chapter_embeddings_video_idx on public.chapter_embeddings (video_id);
