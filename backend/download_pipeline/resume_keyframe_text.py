"""Reads the on-screen text of the keyframes an earlier OCR pass never reached.

Visual indexing deletes its local video file when it ends, so an OCR pass that was
interrupted or failed could never be resumed. This one-off fetches the stored video back
from Blob Storage into a temporary file, reads only the keyframes that still have no OCR
engine on their row, stores what it reads, and deletes the file again.

    python -m backend.download_pipeline.resume_keyframe_text VIDEO_ID           # report only
    python -m backend.download_pipeline.resume_keyframe_text VIDEO_ID --apply   # read and store

Needs AZURE_DATABASE_URL, the Blob Storage settings and VIDSEEK_OCR_PYTHON in `backend/.env`.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from backend.core import config
from backend.services.ocr.surya import SuryaOcrEngine
from backend.storage.blob import BlobVideoStorage
from backend.storage.postgres import PostgresVideoRecords
from backend.storage.postgres.visual_index import PostgresVisualIndex

from .visual_indexing import read_on_screen_text

# Slides full of text take Surya 35 to 200 s a frame on a small GPU, so a batch of four can pass
# the engine's usual 600 s limit; this script waits far longer rather than give up on the video,
# and reads one frame at a time, which also stores progress after every frame.
READ_TIMEOUT_SECONDS = 3600.0

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video_id", help="the id of the video whose unread keyframes to read")
    parser.add_argument("--apply", action="store_true", help="read and store; without it, only report")
    arguments = parser.parse_args(argv)

    store = PostgresVisualIndex()
    record = PostgresVideoRecords().get_by_id(arguments.video_id)
    if record is None:
        logger.error("No video %s", arguments.video_id)
        return 1
    unread_times = store.unread_keyframe_times(arguments.video_id)
    logger.info("%s (%s): %d keyframes unread", arguments.video_id, record.video.title, len(unread_times))
    if not unread_times or not arguments.apply:
        if unread_times:
            logger.info("Nothing written. Run again with --apply to read them.")
        return 0

    python_path = config.ocr_python_path()
    if python_path is None:
        logger.error("VIDSEEK_OCR_PYTHON is not set; there is no OCR engine to read with")
        return 1
    engine = SuryaOcrEngine(
        python_path,
        llama_server_path=config.ocr_llama_server_path(),
        read_timeout_seconds=READ_TIMEOUT_SECONDS,
    )
    try:
        with tempfile.TemporaryDirectory() as folder:
            video_path = BlobVideoStorage().download_video(
                record.video.blob_name, Path(folder) / "video.mp4"
            )
            outcome = read_on_screen_text(
                store,
                arguments.video_id,
                video_path,
                unread_times,
                engine=engine,
                embed_texts=None,
                stop_event=None,
                batch_size=1,
            )
    finally:
        engine.close()
    logger.info(
        "Read %d keyframes, %d show text; %d still unread",
        outcome.keyframes_read,
        outcome.keyframes_with_text,
        store.unread_keyframe_count(arguments.video_id),
    )
    if outcome.problem:
        logger.error("OCR stopped early: %s", outcome.problem)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
