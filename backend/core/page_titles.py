"""Turns a browser tab title into the title of the video on that tab.

The extension sends `document.title`, which is what the tab says rather than what the video
is called. YouTube's tab reads `(3) How Transformers Work - YouTube`: the `(3)` is the
viewer's unread-notification count and the suffix is the site's own name, and neither
belongs to the video.

The cleanup is deliberately narrow, so a title stays close to what the page called it: a
leading notification count goes, and a trailing ` - Site` or ` | Site` goes only when
`Site` is the name of the host the video came from. Anything else is left as it arrived.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# `(3) ` or `(99+) ` at the very start: the unread count some sites prepend to the tab.
NOTIFICATION_COUNT_PREFIX = re.compile(r"^\(\d+\+?\)\s+")
# ` - Name`, ` | Name`, ` – Name` or ` — Name` at the very end, capturing `Name`.
SITE_NAME_SUFFIX = re.compile(r"\s+[-|–—]\s+([^-|–—]+?)\s*$")


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
