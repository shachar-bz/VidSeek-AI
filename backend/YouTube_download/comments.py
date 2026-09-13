"""Fetches a video's top comments from the YouTube Data API v3, ranked by likes.

One request returns up to 100 of the site's own "Top comments" (`order=relevance`),
already ranked by YouTube itself. That is read here rather than reached for through
yt-dlp's comment scraping, which walks the comment section's rendered pages and is far
slower for the same result.

Needs YOUTUBE_API_KEY in backend/.env.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import dotenv_values

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

ENV_FILENAME = ".env"
API_KEY_NAME = "YOUTUBE_API_KEY"

# The API's own ceiling per request; asking for more just returns this many anyway.
MAX_RESULTS_PER_PAGE = 100

DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 30.0

# The `reason` the API gives on a 403 when the uploader has turned comments off, as
# distinct from every other 403 (a bad key, a spent quota), which is worth raising on.
COMMENTS_DISABLED_REASON = "commentsDisabled"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommentEntry:
    """One top-level comment, as ranked by YouTube's own "Top comments" ordering."""

    id: str
    author: str
    text: str
    like_count: int
    reply_count: int
    published_at: str


def _load_api_key() -> str:
    """Read the YouTube Data API key from `backend/.env`, falling back to the environment."""
    env_path = Path(__file__).resolve().parent.parent / ENV_FILENAME
    key = dotenv_values(env_path).get(API_KEY_NAME) or os.environ.get(API_KEY_NAME)
    if not key:
        raise RuntimeError(f"{API_KEY_NAME} is not set in {env_path} or the environment")
    return key


def _error_reasons(response: requests.Response) -> list[str]:
    try:
        return [error.get("reason", "") for error in response.json()["error"]["errors"]]
    except (ValueError, KeyError):
        return []


def _raise_for_error(response: requests.Response, video_id: str) -> None:
    """Raise with the API's own error message, which names the actual problem.

    `response.raise_for_status()` alone would only say "403 Client Error" — not whether
    that means a bad key, a spent quota, or something else worth telling apart.
    """
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError):
        response.raise_for_status()
        return
    raise RuntimeError(f"YouTube Data API refused comments for video {video_id}: {message}")


def _entry_from_thread(thread: dict) -> CommentEntry:
    snippet = thread["snippet"]["topLevelComment"]["snippet"]
    return CommentEntry(
        id=thread["id"],
        author=snippet["authorDisplayName"],
        text=snippet["textOriginal"],
        like_count=snippet["likeCount"],
        reply_count=thread["snippet"]["totalReplyCount"],
        published_at=snippet["publishedAt"],
    )


def fetch_top_comments(
    video_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    max_pages: int = 1,
    api_key: str | None = None,
) -> list[CommentEntry]:
    """Fetch `video_id`'s comments, ranked by like count, at most `limit` of them.

    Reads `order=relevance` pages — YouTube's own "Top comments" — up to `max_pages` of
    them (1 quota unit each), then sorts everything that came back by like count and
    truncates to `limit`. One page already covers `limit=100`; `max_pages` only matters
    for scanning past YouTube's own top page in search of a stricter by-likes ranking.

    A video with comments disabled returns an empty list rather than raising, since the
    video and its transcript are still worth keeping. Anything else the API refuses — a
    bad key, a spent quota — raises with the API's own reason.
    """
    api_key = api_key or _load_api_key()

    entries: list[CommentEntry] = []
    page_token = None
    with requests.Session() as session:
        for _ in range(max_pages):
            params = {
                "part": "snippet",
                "videoId": video_id,
                "order": "relevance",
                "maxResults": MAX_RESULTS_PER_PAGE,
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token

            response = session.get(API_URL, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)

            if response.status_code == 403 and COMMENTS_DISABLED_REASON in _error_reasons(
                response
            ):
                logger.info("Comments are disabled on video %s", video_id)
                return []
            if not response.ok:
                _raise_for_error(response, video_id)

            payload = response.json()
            entries.extend(
                _entry_from_thread(thread) for thread in payload.get("items", [])
            )

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    entries.sort(key=lambda entry: entry.like_count, reverse=True)
    logger.info("Fetched %d comments for video %s", len(entries), video_id)
    return entries[:limit]
