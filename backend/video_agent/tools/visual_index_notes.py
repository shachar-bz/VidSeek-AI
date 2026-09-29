"""What the two visual search tools tell the agent when the video's visual index cannot be searched.

Shared because both searches open the same index and fail the same two ways: it is not built
yet (or failed, or was skipped), or it was built with other models than the ones queries are
embedded with. The visual tools are offered only for a ready index, so this is a turn whose
index changed after it started; the note tells the agent what to say, as the prompt's
not-ready sections do.
"""

from __future__ import annotations

from backend.services.visual_search import INDEX_OUTDATED, VisualSearchResult
from backend.storage.postgres.visual_index import INDEXING, PENDING

from ..prompt import VISUAL_PROCESSING_MESSAGE, VISUAL_UNAVAILABLE_MESSAGE


def unsearchable_note(result: VisualSearchResult) -> str:
    """Why the index could not be searched, and what to tell the user."""
    if result.index_status == INDEX_OUTDATED:
        reason = "The video's visual index was built with other models than the current ones, so it cannot be searched."
    else:
        status = f" (status: {result.visual_status})" if result.visual_status else ""
        reason = f"The video's visual index is not ready{status}, so it cannot be searched."
    message = (
        VISUAL_PROCESSING_MESSAGE
        if result.index_status != INDEX_OUTDATED and result.visual_status in (PENDING, INDEXING)
        else VISUAL_UNAVAILABLE_MESSAGE
    )
    return (
        f"{reason} Answer from what the looks this turn have already shown; for anything else "
        f'about the picture, tell the user, in their language: "{message}"'
    )
