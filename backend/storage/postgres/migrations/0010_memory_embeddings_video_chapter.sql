-- Fixes memory_embeddings now that something actually produces embeddings:
-- backend/services/embeddings/memory_embedding embeds a memory's text with the shared
-- all-MiniLM-L6-v2 model (backend/services/embeddings/model.py), a 384-dimensional model.
--
-- Apply after 0006_memories.sql and 0007_embeddings.sql.
--
-- video_id and chapter_id are denormalized onto this table from memories.video_id and
-- memories.chapter_id, so a similarity search can filter by video or chapter without
-- joining through memories for every row. video_id is not null, mirroring memories.video_id
-- -- every memory belongs to a video. chapter_id stays nullable with `on delete set null`,
-- mirroring memories.chapter_id -- a memory can be embedded before the chapter-grouping
-- stage has run, and this row should not disappear when a chapter is later deleted.
--
-- The embedding column's dimension was left unfixed in 0007 because no model had been
-- chosen yet. It is fixed here at 384, matching the shared all-MiniLM-L6-v2 model. No ANN
-- index (hnsw or ivfflat) is created on it: retrieval and search strategy belong to a
-- dedicated semantic search layer, not to the migration that only stores the vectors.

alter table public.memory_embeddings
    add column if not exists video_id uuid references public.videos (id) on delete cascade,
    add column if not exists chapter_id uuid references public.chapters (id) on delete set null;

update public.memory_embeddings me
    set video_id = m.video_id,
        chapter_id = m.chapter_id
    from public.memories m
    where me.memory_id = m.id and me.video_id is null;

alter table public.memory_embeddings alter column video_id set not null;

alter table public.memory_embeddings alter column embedding type vector(384);

create index if not exists memory_embeddings_video_idx on public.memory_embeddings (video_id);
create index if not exists memory_embeddings_chapter_idx on public.memory_embeddings (chapter_id);
