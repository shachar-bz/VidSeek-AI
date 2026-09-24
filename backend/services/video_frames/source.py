"""Frames of a stored video, read straight out of Blob Storage through a short-lived read link.

This is the query-time half of "no frame is ever stored": indexing reads the local file while
it still exists, and everything after that -- the visual sub-agent looking at the current
frame, a sequence, or a moment search found -- comes from here. The video is never downloaded;
ffmpeg is handed a read-only SAS URL and seeks it over HTTP.

The link is minted per call and lives for minutes, not the hour a playback link does: it only
has to outlast one batch of extractions, and it never leaves this process.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.storage.blob import BlobVideoStorage
from backend.storage.postgres import PostgresVideoRecords

from .extraction import FRAME_LONG_SIDE, ExtractedFrame, extract_frames
from .grid import build_frame_grid, evenly_spaced_times

# Long enough for a batch of seeks over a slow link, short enough to be useless if it leaked.
FRAME_LINK_LIFETIME_SECONDS = 600


class VideoNotStoredError(LookupError):
    """There is no video row, or it names no blob, for the video asked about."""


class VideoFrameSource:
    """Extracts frames of a stored video from its blob, given the video's id."""

    def __init__(
        self,
        *,
        video_records: PostgresVideoRecords | None = None,
        blob_storage: BlobVideoStorage | None = None,
    ):
        self._video_records = video_records or PostgresVideoRecords()
        self._blob_storage = blob_storage

    def frames(
        self,
        video_id: str,
        times: Sequence[float],
        *,
        long_side: int = FRAME_LONG_SIDE,
        lossless: bool = False,
    ) -> list[ExtractedFrame]:
        """The frames at these times, in the same order; PNGs rather than JPEGs if `lossless`."""
        return extract_frames(
            self.read_link(video_id), times, long_side=long_side, lossless=lossless
        )

    def sequence_grid(
        self, video_id: str, start_seconds: float, end_seconds: float, count: int
    ) -> tuple[bytes, list[float]]:
        """`count` frames spread across a window, as one grid JPEG, and the times it shows.

        The window is taken as given. Keeping it inside one scene -- a sequence should never
        straddle a `scene_change` boundary -- is the caller's job, since only the caller
        knows which segment it is asking about.
        """
        times = evenly_spaced_times(start_seconds, end_seconds, count)
        frames = self.frames(video_id, times)
        return build_frame_grid(frames), times

    def read_link(self, video_id: str) -> str:
        """A fresh read-only link to this video's blob. A credential: never log it."""
        record = self._video_records.get_by_id(video_id)
        if record is None or not record.video.blob_name:
            raise VideoNotStoredError(f"Video {video_id} has no stored file")
        if self._blob_storage is None:
            self._blob_storage = BlobVideoStorage()
        return self._blob_storage.sas_download_url(
            record.video.blob_name, FRAME_LINK_LIFETIME_SECONDS
        )
