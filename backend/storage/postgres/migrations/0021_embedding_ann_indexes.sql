-- Approximate-nearest-neighbour indexes on both embedding columns.
--
-- Apply 0010_memory_embeddings_video_chapter.sql and
-- 0011_chapter_embeddings_video_times.sql first: both fixed their `embedding` column at
-- `vector(384)`, and an ANN index cannot be built on a column with no declared dimension.
--
-- 0007, 0010 and 0011 each explained why they added no index: nothing wrote the tables, so
-- a similarity search was a sequential scan over nothing, and choosing an index before
-- there was a single vector to search would have been choosing in the dark. Both are now
-- written on every run -- `backend/download_pipeline/embedding.py` is stage four of the
-- pipeline -- so the scan is no longer over nothing, and `memories_semantic_search` is on
-- the answer path of every question the agent is asked.
--
-- hnsw rather than ivfflat. ivfflat has to be built against rows that already exist and has
-- to be rebuilt as the table grows, because its lists are fitted to the data it saw; hnsw
-- builds incrementally and needs no retraining, which matters here because the tables grow
-- one video at a time and there is nobody to notice that a rebuild is overdue. hnsw costs
-- more to build and more memory; at this scale neither is the binding constraint.
--
-- `vector_cosine_ops` because every search orders by `<=>`, cosine distance:
-- `PostgresMemoryEmbeddings.nearest_memories` does, and all-MiniLM-L6-v2 is trained for it.
-- An index built for a different operator is simply not used by that query, silently, so
-- the operator class has to match the one the search is written against.
--
-- Both searches filter by `video_id` before they order by distance. That filter runs as a
-- post-filter against an hnsw scan, which is why the plain `video_id` btree indexes 0010
-- and 0011 added are kept rather than replaced: a video with few memories is still better
-- served by reading its own rows and sorting them.

create index if not exists memory_embeddings_embedding_hnsw_idx
    on public.memory_embeddings
    using hnsw (embedding vector_cosine_ops);

create index if not exists chapter_embeddings_embedding_hnsw_idx
    on public.chapter_embeddings
    using hnsw (embedding vector_cosine_ops);
