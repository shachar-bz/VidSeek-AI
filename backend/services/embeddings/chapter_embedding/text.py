"""The text a chapter is embedded from.

A chapter's own contribution is its `title` and `summary` (see
`backend.semantic_segmentation.chapters`); both come from the `chapters` table.
"""


def build_embedding_text(title: str, summary: str) -> str:
    """Render one chapter's title and summary as the text passed to `embed_text`."""
    return f"chapter title: {title}\nchapter summary: {summary}"
