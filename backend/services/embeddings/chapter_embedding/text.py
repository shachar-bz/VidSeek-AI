"""The text a chapter is embedded from.

A chapter's own contribution is its `title` and `summary` (see
`backend.services.semantic_segmentation.chapters`); both come from the `chapters` table.
"""


def build_embedding_text(title: str, summary: str) -> str:
    """Render one chapter's title and summary as the passage passed to `embed_passages`."""
    return f"chapter title: {title}\nchapter summary: {summary}"
