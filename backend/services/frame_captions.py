"""Keeps the captions the visual sub-agent writes, so each part of a video is paid for once.

Whenever the sub-agent has to look at pixels -- one frame, or a grid of a sequence -- it also
writes a short, general caption of what it saw: what is visible, where things are, what is
happening. Not an answer to the question it was asked, because a caption slanted towards one
question is useless for the next. `save_frame_captions` embeds those captions with
multilingual-e5-small and stores them, and from then on the visual search and the segment map
read them as text before anyone pays for an image of that moment again.

Nothing calls this during ingestion: at ingestion a video has no captions at all, and they
accumulate only as people ask about it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.storage.postgres import NewFrameCaption, PostgresFrameCaptions


@dataclass(frozen=True)
class CaptionToSave:
    """One caption the sub-agent wrote, for a frame or for a sequence window."""

    time_seconds: float
    caption: str
    # Set for a caption of a sequence grid, which describes a window rather than one frame.
    end_seconds: float | None = None


def save_frame_captions(
    video_id: str,
    captions: Sequence[CaptionToSave],
    *,
    model: str,
    pool=None,
) -> int:
    """Embed and store these captions for this video, and say how many were kept.

    `model` is the VLM that wrote them. Blank captions are dropped rather than stored as
    vectors of nothing.
    """
    kept = [caption for caption in captions if caption.caption.strip()]
    if not kept:
        return 0
    # Imported here so that importing this module does not load the embedding model.
    from backend.services.embeddings.multilingual_text_embedding import embed_passages

    vectors = embed_passages([caption.caption.strip() for caption in kept])
    return PostgresFrameCaptions(pool=pool).add(
        video_id,
        [
            NewFrameCaption(
                time_seconds=caption.time_seconds,
                end_seconds=caption.end_seconds,
                caption=caption.caption.strip(),
                embedding=vector,
                model=model,
            )
            for caption, vector in zip(kept, vectors)
        ],
    )
