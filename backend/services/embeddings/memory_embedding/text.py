"""The text a memory is embedded from.

A memory's own contribution is its `summary` (see `backend.semantic_segmentation.memories`)
and its raw `text`; its chapter's `title` is included alongside them so the vector also
carries the broader section a memory belongs to, which is often what a search query names
rather than the memory's own narrower point. A memory not yet grouped into a chapter has no
title to give, so that line is left out rather than written empty.
"""


def build_embedding_text(chapter_title: str | None, summary: str, text: str) -> str:
    """Render one memory's chapter title, summary, and raw text as the text passed to `embed_text`."""
    lines = []
    if chapter_title:
        lines.append(f"chapter title: {chapter_title}")
    lines.append(f"memory summary: {summary}")
    lines.append(f"memory text: {text}")
    return "\n".join(lines)
