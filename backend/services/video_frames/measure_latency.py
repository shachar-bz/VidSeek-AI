"""Measures how long a batch of on-demand frames takes out of Blob Storage, for one stored video.

VISUAL_UNDERSTANDING_PLAN.md decides between extracting every frame on demand and adding a
keyframe JPEG cache on this number: a cache is worth building only if one tool call's batch of
frames takes more than about one to two seconds. Seeking a WebM with no seek index over HTTP is
the case most likely to be slow, so run this against a WebM as well as an MP4.

Run it from the repository root, with the video's id from the `videos` table:

    python -m backend.services.video_frames.measure_latency <video_id>
    python -m backend.services.video_frames.measure_latency <video_id> --frames 6 --rounds 3

Needs AZURE_DATABASE_URL, AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_CONTAINER_NAME in
`backend/.env`, and ffmpeg on PATH. Nothing is written anywhere; the frames are discarded.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time

from backend.storage.postgres import PostgresVideoRecords

from .extraction import FrameExtractionError, extract_frame, extract_frames
from .source import VideoFrameSource


def main(argv: list[str] | None = None) -> int:
    """Time single frames and parallel batches at random times across the video."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video_id")
    parser.add_argument("--frames", type=int, default=6, help="frames per batch (default 6)")
    parser.add_argument("--rounds", type=int, default=3, help="batches to time (default 3)")
    arguments = parser.parse_args(argv)

    record = PostgresVideoRecords().get_by_id(arguments.video_id)
    if record is None or not record.video.blob_name:
        print(f"Video {arguments.video_id} has no stored file", file=sys.stderr)
        return 1
    duration = record.video.duration_seconds or 60.0
    link = VideoFrameSource().read_link(arguments.video_id)
    print(f"{record.video.blob_name} ({record.video.content_type}), {duration:.0f} s")

    try:
        single = []
        for _ in range(arguments.rounds):
            started = time.perf_counter()
            extract_frame(link, random.uniform(0, duration * 0.95))
            single.append(time.perf_counter() - started)
        print(f"one frame: median {statistics.median(single):.2f} s, max {max(single):.2f} s")

        batches = []
        for _ in range(arguments.rounds):
            times = sorted(random.uniform(0, duration * 0.95) for _ in range(arguments.frames))
            started = time.perf_counter()
            extract_frames(link, times)
            batches.append(time.perf_counter() - started)
        print(
            f"{arguments.frames} frames in parallel: median {statistics.median(batches):.2f} s, "
            f"max {max(batches):.2f} s"
        )
    except FrameExtractionError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
