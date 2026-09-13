"""Downloads a YouTube video to a local file with yt-dlp.

YouTube serves video and audio as separate streams for anything above 360p, so the two
best of them are fetched and muxed back together into one MP4 by ffmpeg, which this
project already requires on PATH for its other modules.

Files are named by YouTube's own video id rather than by title: titles collide between
videos, change under you between runs, and are full of characters no filesystem wants.
The id is also what the Data API wants for the comments, so the download is what supplies
it to the rest of the module.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from yt_dlp import YoutubeDL

# The best video track and the best audio track merged, falling back to the best single
# already-muxed stream for videos that have no separate tracks to merge.
FORMAT_SELECTOR = "bestvideo+bestaudio/best"
MERGE_CONTAINER = "mp4"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadedVideo:
    """A video that is now on local disk, and the identity YouTube knows it by."""

    video_id: str
    title: str
    video_path: str


def build_download_options(output_dir: Path) -> dict:
    """yt-dlp options shared by every call this module makes.

    `noplaylist` is the load-bearing one: an ordinary watch URL copied out of the browser
    usually carries a `&list=` alongside the video id, and without this yt-dlp obligingly
    downloads the entire playlist that video happens to sit in.
    """
    return {
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }


def download_video(url: str, output_dir: str | Path) -> DownloadedVideo:
    """Download the video at `url` into `output_dir` as a single MP4."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    options = build_download_options(output_dir) | {
        "format": FORMAT_SELECTOR,
        "merge_output_format": MERGE_CONTAINER,
    }

    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)

    # The path has to come from `requested_downloads` rather than from the output template:
    # after a merge the file carries the container's extension, not the one the chosen
    # video track started out with.
    downloads = info.get("requested_downloads") or []
    video_path = downloads[0].get("filepath") if downloads else None
    if not video_path:
        raise RuntimeError(f"yt-dlp reported no downloaded file for {url}")

    logger.info("Downloaded %s to %s", url, video_path)
    return DownloadedVideo(
        video_id=info["id"],
        title=info.get("title", ""),
        video_path=video_path,
    )
