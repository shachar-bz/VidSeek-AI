-- The comment_embeddings table: one meaning vector per YouTube comment, for the conversation
-- agent's comment search.
--
-- Apply 0004_comments.sql first; every row here points at a comment.
--
-- 0004 said comments were not meant to be searched semantically. That changed with the
-- agent's `get_viewer_comments` tool, which answers "what did people say about the ending"
-- by meaning, so a paraphrase ("the last scene") still finds it.
--
-- A table of its own rather than a column on `comments`, the same split as memories and
-- `memory_embeddings`: a comment is written at Store and its vector later, by the embedding
-- step, and an old video's comments exist with no vector at all.
--
-- multilingual-e5-small rather than the MiniLM the memories use: comment sections are as
-- often Hebrew as English, and MiniLM reads English only. Its vectors are L2-normalized.

create table if not exists public.comment_embeddings (
    -- The comment's own YouTube id, which is `comments`' primary key. A re-fetch that no
    -- longer brings a comment back trims its row from `comments`, and its vector with it.
    comment_id text primary key references public.comments (id) on delete cascade,

    -- Repeated from `comments` so one video's vectors are read on their own index, the
    -- reason 0010 gave `memory_embeddings` a video_id.
    video_id uuid not null references public.videos (id) on delete cascade,

    embedding vector(384) not null,
    model text not null,

    created_at timestamptz not null default now()
);

comment on table public.comment_embeddings is
    'One multilingual-e5-small vector per YouTube comment, for searching a video''s comments by meaning.';

-- No ANN index, for the reason `video_keyframes.ocr_embedding` has none: a search is about one
-- video, whose few hundred comments are cheap to score exactly.
create index if not exists comment_embeddings_video_idx
    on public.comment_embeddings (video_id);
