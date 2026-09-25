"""Stage four: the memories and chapters become vectors, which is what makes a video searchable.

Both embedding pipelines already exist and both read what they embed out of the database
rather than taking it from a caller, so this stage passes them a video id and nothing else.
That is also what makes the stage re-runnable on its own: nothing it needs is still held in
the process that produced it, so a video whose embeddings failed can be embedded later
without being downloaded, transcribed or segmented again.

Memories are embedded before chapters because a memory's vector is built from its chapter's
title alongside its own text, so the join it reads is only complete once stage three has
written both. Chapters are embedded second and would work in either order; keeping them
second means the more important of the two — the memories are what a semantic search
actually matches against — is attempted first when something is about to go wrong.

A YouTube video's comments are embedded separately, by `embed_comments`, because they do not
wait on a transcript: they are stored with the video, and a video no transcript could be
divided for still has comments worth searching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .result import COMMENT_EMBEDDING_FAILED, EMBEDDING_FAILED

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddedVideo:
    """How many vectors this run wrote, and whether it managed to write them all."""

    memory_count: int = 0
    chapter_count: int = 0
    problems: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EmbeddedComments:
    """How many comment vectors this run wrote, and whether it managed to write them."""

    comment_count: int = 0
    problems: tuple[str, ...] = field(default_factory=tuple)


def embed_video(video_id: str, *, pool=None) -> EmbeddedVideo:
    """Embed and store this video's memories and chapters, reporting a failure rather than raising.

    Reported rather than raised for the same reason stage three reports: everything the
    vectors are built from is already in the database, so a failure here costs the video its
    searchability until the stage is run again, not its download. Both pipelines are
    attempted under one guard because they fail for the same reasons — the embedding model
    or the database — and a run that could not embed the memories has no prospect of
    embedding the chapters.
    """
    # Imported here rather than at module scope because reaching either pipeline loads the
    # shared sentence-transformers model, which is hundreds of megabytes and several seconds
    # of startup. Everything upstream of this stage -- the job manager, the API that builds
    # it -- would otherwise pay for it on import, including on a run that never embeds
    # anything because the video had no transcript to divide.
    from backend.services.embeddings.chapter_embedding import embed_chapters_for_video
    from backend.services.embeddings.memory_embedding import embed_memories_for_video

    try:
        memory_count = embed_memories_for_video(video_id, pool=pool)
        chapter_count = embed_chapters_for_video(video_id, pool=pool)
    except Exception:
        logger.exception("Embedding video %s failed", video_id)
        return EmbeddedVideo(problems=(EMBEDDING_FAILED,))

    return EmbeddedVideo(memory_count=memory_count, chapter_count=chapter_count)


def embed_comments(video_id: str, *, pool=None) -> EmbeddedComments:
    """Embed and store this video's comments, reporting a failure rather than raising.

    The comments stay stored and readable whatever happens here; a failure only costs the
    agent searching them by topic, which falls back to the best-liked ones.
    """
    # Imported here for the reason `embed_video` gives: it loads a sentence-transformers model.
    from backend.services.embeddings.comment_embedding import embed_comments_for_video

    try:
        comment_count = embed_comments_for_video(video_id, pool=pool)
    except Exception:
        logger.exception("Embedding the comments of video %s failed", video_id)
        return EmbeddedComments(problems=(COMMENT_EMBEDDING_FAILED,))
    return EmbeddedComments(comment_count=comment_count)
