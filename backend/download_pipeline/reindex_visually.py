"""Builds one stored video's visual index again, from its copy in Blob Storage.

The job manager already does this by itself, each time it starts, for every video an earlier
shutdown interrupted. This one-off is for a video it will not pick up: one whose index failed
for another reason, or that was skipped, or one to index now rather than at the next start.
It refuses a video whose index is `ready`, or that says `indexing` while a process may still
be building it: one that has not changed for `ABANDONED_AFTER` is taken as abandoned.

    python -m backend.download_pipeline.reindex_visually VIDEO_ID           # report only
    python -m backend.download_pipeline.reindex_visually VIDEO_ID --apply   # index and store

Needs AZURE_DATABASE_URL and the Blob Storage settings in `backend/.env`, and VIDSEEK_OCR_PYTHON
for the keyframes' text; without it they are left unread, for `resume_keyframe_text` to read.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend.services.ocr import configured_ocr_engine
from backend.storage.postgres import PostgresVideoRecords
from backend.storage.postgres.visual_index import FAILED, PENDING, READY, SKIPPED, PostgresVisualIndex

from .visual_indexing import is_abandoned, reindex_video_visually

# The statuses of a video that has no index and none being built.
REINDEXABLE_STATUSES = (PENDING, FAILED, SKIPPED)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video_id", help="the id of the video to index again")
    parser.add_argument("--apply", action="store_true", help="index and store; without it, only report")
    arguments = parser.parse_args(argv)

    record = PostgresVideoRecords().get_by_id(arguments.video_id)
    state = PostgresVisualIndex().state(arguments.video_id)
    if record is None or state is None:
        logger.error("No video %s", arguments.video_id)
        return 1
    logger.info(
        "%s (%s): visual status %s, error %s",
        arguments.video_id,
        record.video.title,
        state.status,
        state.error,
    )
    abandoned = is_abandoned(state, now=datetime.now(timezone.utc))
    if state.status not in REINDEXABLE_STATUSES and not abandoned:
        logger.error(
            "Only a video whose status is one of %s, or an abandoned index, is indexed again",
            ", ".join(REINDEXABLE_STATUSES),
        )
        return 1
    if not arguments.apply:
        logger.info("Nothing written. Run again with --apply to index it.")
        return 0

    with tempfile.TemporaryDirectory() as folder:
        outcome = reindex_video_visually(
            arguments.video_id, Path(folder), ocr_engine=configured_ocr_engine()
        )
    logger.info("Outcome: %s", outcome)
    return 0 if outcome.status == READY and outcome.ocr_problem is None else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
