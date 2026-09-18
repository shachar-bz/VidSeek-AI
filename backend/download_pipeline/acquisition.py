"""Stage one: get the video onto this machine, with a timed transcript beside it.

Nothing is downloaded or transcribed here. Three services already do that, one per way a
video can reach us, and this module is only the dispatch between them — which is worth a
module of its own because the choice is the one thing a caller has to make before the rest
of the pipeline becomes identical for all three.

The transcript precedence the pipeline promises lives inside those services rather than
here, and is the same wherever the video came from:

* captions the page or the download already supplied, which are free and already timed;
* a transcript supplied without timing, fitted onto the video's audio by forced alignment
  rather than thrown away and transcribed again;
* ElevenLabs' Scribe, for a video with no transcript anywhere.

All three routes return the same `PipelineResult`, whose `normalized_transcript` is the
timed transcript every later stage reads and whose `transcript_error` says when there is
none. A route that could not get the video at all raises instead, because there is no
partial version of a video that was never downloaded.
"""

from __future__ import annotations

import threading
from enum import Enum
from pathlib import Path

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.video_download.web.downloader import DownloadedVideo
from backend.services.video_download.web.pipeline import (
    PipelineResult,
    download_and_transcribe,
    process_downloaded_video,
)
from backend.services.video_download.youtube_job import run_youtube_job


class AcquisitionRoute(str, Enum):
    """How this video reaches the machine the pipeline runs on.

    The route is decided before a job starts — a YouTube page needs YouTube's own pipeline,
    a direct media file is fetched by Chrome so the page's cookies apply, and everything
    else is fetched by the companion — so it is passed in rather than re-derived here.
    """

    # A YouTube URL: yt-dlp for the video, YouTube's caption track or Scribe for the
    # transcript, and the Data API for the comments no other route has.
    YOUTUBE = "youtube"

    # The companion fetches the media itself, using the browser context the extension
    # captured, for a page whose video is not a plain file Chrome could download.
    COMPANION_DOWNLOAD = "companion_download"

    # Chrome already downloaded the file; the pipeline picks it up where Chrome left it.
    DOWNLOADED_FILE = "downloaded_file"


def acquire_video(
    route: AcquisitionRoute,
    *,
    request: CreateVideoJobRequest,
    download_root: Path,
    cancel_event: threading.Event,
    progress_callback,
    local_path: Path | None = None,
) -> PipelineResult:
    """Run `route`'s download-and-transcribe service, and return what it produced.

    `local_path` is required by `DOWNLOADED_FILE` and meaningless to the other two: it is
    the file Chrome wrote, already validated to sit under the download root by whoever
    accepted it from the browser.

    Raises whatever the underlying service raises. A caller that needs to tell a failed
    download apart from a failed transcript does not have to: `process_downloaded_video`
    reports every transcript failure on a successful result, so an exception out of here
    always means the video itself was not obtained.
    """
    if route is AcquisitionRoute.YOUTUBE:
        return run_youtube_job(
            request=request,
            download_root=download_root,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )

    if route is AcquisitionRoute.COMPANION_DOWNLOAD:
        return download_and_transcribe(
            request=request,
            download_root=download_root,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )

    if local_path is None:
        raise ValueError("The downloaded-file route needs the path Chrome wrote to")
    return process_downloaded_video(
        video=DownloadedVideo(title=request.page_title, video_path=local_path),
        request=request,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )
