-- The embedding tables: one vector per memory, and one per chapter.
--
-- Apply 0001_extensions.sql (which creates `vector`), 0005_chapters.sql and
-- 0006_memories.sql first.
--
-- Placeholders, and more so than the two tables they point at: nothing in this project
-- computes an embedding at all yet, and no embedding model has been chosen. That choice is
-- the reason these are separate tables rather than a column on `memories` and `chapters`.
-- A vector column's dimension is fixed when the column is created, so putting one on those
-- tables would have meant either guessing a model now or altering a table that holds real
-- rows later; a table of its own can be emptied and recreated without touching the text it
-- describes.
--
-- The `embedding` columns are therefore declared as bare `vector`, with no dimension.
-- pgvector allows this, and it is the honest declaration while no model has been picked:
-- a row of any width can be stored. What it cannot have is an ANN index -- ivfflat and
-- hnsw both need a fixed dimension -- so there is none here, and a similarity search
-- against these tables would be a sequential scan. Fixing the dimension and adding the
-- index is one later migration, once something is actually producing vectors:
--
--   alter table public.memory_embeddings alter column embedding type vector(1536);
--   create index on public.memory_embeddings using hnsw (embedding vector_cosine_ops);
--
-- `model` and `dimensions` record what produced each vector, so that a table holding two
-- generations of embedding can be told apart and migrated rather than guessed at.

create table if not exists public.memory_embeddings (
    id uuid primary key default gen_random_uuid(),

    -- One embedding per memory, which the unique constraint is what enforces: the
    -- relationship is one-to-one, and a second vector for the same memory would leave
    -- every reader to decide which one counts.
    memory_id uuid not null references public.memories (id) on delete cascade,

    embedding vector,
    model text,
    dimensions integer,

    created_at timestamptz not null default now(),

    constraint memory_embeddings_memory_unique unique (memory_id),
    constraint memory_embeddings_dimensions_positive check (dimensions is null or dimensions > 0)
);

comment on table public.memory_embeddings is
    'One vector per memory; no dimension fixed and no index yet, because nothing embeds anything.';


create table if not exists public.chapter_embeddings (
    id uuid primary key default gen_random_uuid(),

    -- One embedding per chapter, for the same reason as above.
    chapter_id uuid not null references public.chapters (id) on delete cascade,

    embedding vector,
    model text,
    dimensions integer,

    created_at timestamptz not null default now(),

    constraint chapter_embeddings_chapter_unique unique (chapter_id),
    constraint chapter_embeddings_dimensions_positive check (dimensions is null or dimensions > 0)
);

comment on table public.chapter_embeddings is
    'One vector per chapter; no dimension fixed and no index yet, because nothing embeds anything.';
