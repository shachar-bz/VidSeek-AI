"""Embeds a video's memories and stores the vectors in `memory_embeddings`.

Reads each memory from PostgreSQL (`memories`, joined to its chapter for `title`), embeds
`text.build_embedding_text`'s rendering of it with the shared model, and writes the result
back, keyed on the memory. `PostgresMemoryEmbeddings.replace` is what makes this safe to run
again after memories or chapters change: it overwrites every memory's vector in place and
drops any the run no longer produced.

Needs AZURE_DATABASE_URL in `backend/.env`, and the migrations up to
`0010_memory_embeddings_video_chapter.sql` applied.
"""

from __future__ import annotations

import logging

from backend.services.embeddings.model import MODEL_NAME, embed_text
from backend.storage.postgres import MemoryEmbedding, PostgresMemoryEmbeddings

from .text import build_embedding_text

logger = logging.getLogger(__name__)


def embed_memories_for_video(video_id: str, *, pool=None) -> int:
    """Embed and store every memory of one video, and return how many were written."""
    store = PostgresMemoryEmbeddings(pool=pool)
    memories = store.memories_for_video(video_id)

    embeddings = []
    for memory in memories:
        text = build_embedding_text(memory.chapter_title, memory.summary)
        vector = embed_text(text)
        embeddings.append(
            MemoryEmbedding(
                memory_id=memory.memory_id,
                chapter_id=memory.chapter_id,
                embedding=vector,
                model=MODEL_NAME,
                dimensions=len(vector),
            )
        )

    written = store.replace(video_id, embeddings)
    logger.info("Embedded %d memories for video %s", written, video_id)
    return written
