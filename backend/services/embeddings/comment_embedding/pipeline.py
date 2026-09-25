"""Embeds a video's YouTube comments and stores the vectors in `comment_embeddings`.

Reads the comments back from PostgreSQL rather than taking them from a caller, so it can be
run again on its own. multilingual-e5-small rather than the shared MiniLM, because comment
sections are as often Hebrew as English; all of a video's comments go through it as one
batch, since there are at most a few hundred of them and each is short.

Needs AZURE_DATABASE_URL in `backend/.env`, and `0027_comment_embeddings.sql` applied.
"""

from __future__ import annotations

import logging

from backend.services.embeddings.multilingual_text_embedding import MODEL_NAME, embed_passages
from backend.storage.postgres import CommentEmbedding, PostgresCommentEmbeddings, PostgresComments

logger = logging.getLogger(__name__)


def embed_comments_for_video(video_id: str, *, pool=None) -> int:
    """Embed and store every stored comment of one video, and return how many were written."""
    comments = PostgresComments(pool=pool).load(video_id)
    vectors = embed_passages([comment.text for comment in comments])
    written = PostgresCommentEmbeddings(pool=pool).replace(
        video_id,
        [
            CommentEmbedding(comment_id=comment.id, embedding=vector, model=MODEL_NAME)
            for comment, vector in zip(comments, vectors)
        ],
    )
    logger.info("Embedded %d comments for video %s", written, video_id)
    return written
