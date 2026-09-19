"""Reduces a page URL to what identifies the video on it, for deduplication.

`videos.source_url` keeps the URL the extension actually sent, which is the right thing to
keep and the wrong thing to compare. `youtu.be/X`, `youtube.com/watch?v=X`, either of them
with `&t=42`, and either of them again carrying a `utm_source` are four spellings of one
video, and a companion that compares them literally downloads, transcribes, segments and
embeds that video four times.

This module is the comparison. `normalize_source_url` is the definition of
`videos.normalized_source_url` (see `migrations/0019_videos_normalized_source_url.sql`);
nothing computes that column any other way, and the unique index on it is only meaningful
while that stays true.

The normalization is deliberately conservative outside YouTube. Two URLs are collapsed only
where the difference between them is known to carry no meaning -- the scheme, a `www.`, a
default port, a fragment, the order of query parameters, and a fixed list of tracking
parameters. Anything else is left alone, because a query parameter this module does not
recognise is far more likely to select which video a page shows than to be noise.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .security import is_youtube_url

# Analytics and click-attribution parameters. None of them changes which video a page
# shows, and all of them travel on links that are otherwise identical -- which is exactly
# the case this column exists to collapse.
TRACKING_PARAMETERS = frozenset(
    {
        "_ga",
        "fbclid",
        "gbraid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref_src",
        "si",
        "ttclid",
        "twclid",
        "utm_campaign",
        "utm_content",
        "utm_id",
        "utm_medium",
        "utm_source",
        "utm_term",
        "wbraid",
        "yclid",
    }
)

# Ports that add nothing to a URL, since the scheme already implies them.
DEFAULT_PORTS = {"http": 80, "https": 443}

# The one scheme a normalized URL is written under. http and https addressing the same page
# is a redirect rather than a second video, and keeping both would defeat the whole column
# on any site that serves either.
CANONICAL_SCHEME = "https"

# The YouTube path shapes that carry a video id as their last segment. `watch` is absent
# because it carries the id in `?v=` instead, which is handled separately.
YOUTUBE_ID_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")

# Every YouTube video reduces to this, whichever of the five shapes it arrived in.
YOUTUBE_CANONICAL = "https://www.youtube.com/watch?v={video_id}"


def normalize_source_url(url: str) -> str:
    """The form of `url` that identifies the video on it, for comparing against other URLs.

    Returns the input stripped of whitespace if it cannot be parsed as an http(s) URL with a
    hostname. Nothing is raised: this is used to key a row, not to validate a request --
    `core.security.validate_remote_url` is the gate that rejects a URL -- and a value that
    is only ever compared against other values of itself is still a usable key even when it
    is a URL this function did not understand.
    """
    trimmed = url.strip()
    parsed = urlsplit(trimmed)
    if parsed.scheme.lower() not in DEFAULT_PORTS or not parsed.hostname:
        return trimmed

    if is_youtube_url(trimmed):
        video_id = youtube_video_id(trimmed)
        if video_id:
            return YOUTUBE_CANONICAL.format(video_id=video_id)

    return urlunsplit(
        (
            CANONICAL_SCHEME,
            _netloc(parsed),
            _path(parsed.path),
            _query(parsed.query),
            # The fragment is never sent to the server, so it cannot select a different
            # video; on a single-page site it selects a view of the same one.
            "",
        )
    )


def youtube_video_id(url: str) -> str | None:
    """The eleven-character video id a YouTube URL names, or None if it names none.

    Five shapes carry one: `youtu.be/<id>`, `watch?v=<id>`, `shorts/<id>`, `embed/<id>` and
    `live/<id>`. A channel page, a playlist page or a search result carries none, and is
    left for the generic normalization to handle as an ordinary page.
    """
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path

    if hostname == "youtu.be":
        return _first_path_segment(path)

    for prefix in YOUTUBE_ID_PATH_PREFIXES:
        if path.startswith(prefix):
            return _first_path_segment(path.removeprefix(prefix))

    for name, value in parse_qsl(parsed.query, keep_blank_values=False):
        if name == "v" and value:
            return value
    return None


def _first_path_segment(path: str) -> str | None:
    """The first non-empty segment of `path`, or None if it has none."""
    for segment in path.split("/"):
        if segment:
            return segment
    return None


def _netloc(parsed) -> str:
    """The host, lower-cased, without `www.` and without a port the scheme already implies.

    Credentials are dropped rather than kept: they say who is reading the page, not which
    page is being read, and `core.security.validate_remote_url` refuses them anyway.
    """
    host = (parsed.hostname or "").lower().removeprefix("www.")
    port = parsed.port
    if port is None or port == DEFAULT_PORTS.get(parsed.scheme.lower()):
        return host
    return f"{host}:{port}"


def _path(path: str) -> str:
    """The path with a trailing slash removed, since `/watch/` and `/watch` are one page.

    The root path is left as an empty string rather than as `/`, which is what `urlunsplit`
    produces for a host with no path anyway, so that `example.com` and `example.com/` agree.
    """
    return path.rstrip("/")


def _query(query: str) -> str:
    """The query with tracking parameters dropped and the rest sorted.

    Sorted because `?a=1&b=2` and `?b=2&a=1` are one request, and a dictionary would have
    lost a repeated parameter -- `?tag=x&tag=y` is meaningful to plenty of sites -- so the
    pairs are sorted as pairs instead.
    """
    kept = [
        (name, value)
        for name, value in parse_qsl(query, keep_blank_values=True)
        if name.lower() not in TRACKING_PARAMETERS
    ]
    return urlencode(sorted(kept))
