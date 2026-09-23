"""Turns a browser tab title into the title of the video on that tab.

The extension sends `document.title`, which is what the tab says rather than what the video
is called. YouTube's tab reads `(3) How Transformers Work - YouTube`: the `(3)` is the
viewer's unread-notification count and the suffix is the site's own name, and neither
belongs to the video.

The cleanup is deliberately narrow, so a title stays close to what the page called it: a
leading notification count goes, and a trailing ` - Site` or ` | Site` goes only when
`Site` is the name of the host the video came from. Anything else is left as it arrived.

Some tabs have no title worth the name: the extension falls back to `video` when a page gives
none, and a YouTube tab that has not loaded yet reads only `YouTube`. `display_title` shows
such a video as `Coursera video, Sep 23, 2026` instead, so a library of nameless videos can
still be told apart.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

# `(3) ` or `(99+) ` at the very start: the unread count some sites prepend to the tab.
NOTIFICATION_COUNT_PREFIX = re.compile(r"^\(\d+\+?\)\s+")
# ` - Name`, ` | Name`, ` – Name` or ` — Name` at the very end, capturing `Name`.
SITE_NAME_SUFFIX = re.compile(r"\s+[-|–—]\s+([^-|–—]+?)\s*$")
# What the extension sends when a page has no title of its own.
PLACEHOLDER_TITLES = frozenset({"", "video"})
# Hosts whose service name is not simply their first label, capitalized.
PLATFORM_NAMES = {"youtube": "YouTube", "youtu": "YouTube", "drive": "Google Drive", "vimeo": "Vimeo"}


def _site_names(page_url: str) -> set[str]:
    """The host's labels bar its top-level domain, lower-cased: `m.youtube.com` -> m, youtube."""
    labels = (urlsplit(page_url).hostname or "").split(".")[:-1]
    names = set(labels)
    if "youtu" in names:
        names.add("youtube")
    return names


def clean_page_title(page_title: str, page_url: str) -> str:
    """The video's title with the tab's notification count and site-name suffix removed.

    Falls back to the title as given when cleaning would leave nothing.
    """
    title = NOTIFICATION_COUNT_PREFIX.sub("", page_title.strip())
    suffix = SITE_NAME_SUFFIX.search(title)
    if suffix and suffix.group(1).replace(" ", "").lower() in _site_names(page_url):
        title = title[: suffix.start()]
    return title.strip() or page_title.strip()


def platform_name(page_url: str) -> str:
    """The platform a page belongs to, as people call it: YouTube, Coursera, Vimeo."""
    labels = (urlsplit(page_url).hostname or "").removeprefix("www.").split(".")[:-1]
    for label in labels:
        if label in PLATFORM_NAMES:
            return PLATFORM_NAMES[label]
    return labels[0].capitalize() if labels else ""


def _is_placeholder(title: str, page_url: str) -> bool:
    name = title.strip().lower()
    return name in PLACEHOLDER_TITLES or name.replace(" ", "") in _site_names(page_url)


def display_title(page_title: str, page_url: str, added_at: str | None = None) -> str:
    """The title to show for a video: its cleaned tab title, or a label when it has none.

    `added_at` is an ISO timestamp; it dates the label so that two nameless videos from one
    platform read differently, and is left off when missing or unreadable.
    """
    title = clean_page_title(page_title, page_url)
    if not _is_placeholder(title, page_url):
        return title
    label = f"{platform_name(page_url) or 'Untitled'} video"
    try:
        added = datetime.fromisoformat(added_at) if added_at else None
    except ValueError:
        added = None
    return f"{label}, {added:%b} {added.day}, {added.year}" if added else label
