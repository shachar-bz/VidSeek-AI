"""Chooses which of the browser's request headers may be replayed to a media server."""

from __future__ import annotations

from backend.schemas.browser import BrowserContext

ALLOWED_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "authorization", "origin", "referer", "user-agent"}
)


def filtered_headers(
    context: BrowserContext,
    candidate_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Copy only request headers needed to reproduce a media request.

    Chrome's debugger reports header names lowercased, so names are folded to one
    canonical spelling here; otherwise a captured `user-agent` and the popup's own
    `User-Agent` would both be sent and yt-dlp would pick between them arbitrarily.
    """
    combined: dict[str, tuple[str, str]] = {}
    for name, value in {**context.headers, **(candidate_headers or {})}.items():
        combined[name.lower()] = (name, value)
    if context.user_agent:
        combined.setdefault("user-agent", ("User-Agent", context.user_agent))

    return {
        name: value
        for lowered, (name, value) in combined.items()
        if lowered in ALLOWED_REQUEST_HEADERS
        and "\r" not in value
        and "\n" not in value
    }
