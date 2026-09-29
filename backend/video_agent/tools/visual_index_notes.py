"""What the two visual search tools tell the agent when the video's visual index cannot be searched.

Shared because both searches open the same index and fail the same two ways: it is not built
yet (or failed, or was skipped), or it was built with other models than the ones queries are
embedded with. Either way, a look at the frames still works, so the note sends the agent there.
"""

from __future__ import annotations

from backend.services.visual_search import INDEX_OUTDATED, VisualSearchResult


def unsearchable_note(result: VisualSearchResult) -> str:
    """Why the index could not be searched, and what to do instead."""
    if result.index_status == INDEX_OUTDATED:
        reason = "The video's visual index was built with other models than the current ones, so it cannot be searched."
    else:
        status = f" (status: {result.visual_status})" if result.visual_status else ""
        reason = f"The video's visual index is not ready{status}, so it cannot be searched."
    return (
        f"{reason} Look with view_sequence across the part the question is about, or around the "
        "viewer's position, and say the video was only sampled."
    )
