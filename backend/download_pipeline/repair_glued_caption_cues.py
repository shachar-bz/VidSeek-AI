"""Repairs the videos stored while the caption parser swallowed cues that had no blank line before them.

Such a video's transcript holds the swallowed cue's timing line as speech, and that cue's
words timed as the cue before it, so every memory built on it reads wrong and cites early.
The stored text still carries each glued timing line, which is all the repair needs: the
segments are split back into cues at those lines, normalized again, and stored in place of
the old ones, and stages three to five are run again on the result.

    python -m backend.download_pipeline.repair_glued_caption_cues            # report only
    python -m backend.download_pipeline.repair_glued_caption_cues --apply    # repair

Stages three and five call the LLM once per video each. Needs AZURE_DATABASE_URL in
`backend/.env`.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from backend.core.captions import GLUED_TIMING_PATTERN, split_glued_cues
from backend.services.transcripts import NormalizedTranscript, normalize_caption_cues
from backend.storage.postgres import PostgresTranscriptSegments, PostgresVideoRecords

from .embedding import embed_video
from .insights import generate_and_store_insights
from .segmentation import segment_and_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairPlan:
    """One affected video's transcript as stored, and as it will be once repaired."""

    video_id: str
    title: str
    stored_segment_count: int
    glued_segment_count: int
    repaired: NormalizedTranscript


def plan_repairs(*, pool=None) -> list[RepairPlan]:
    """What repairing every affected video would write, without writing anything."""
    segments_store = PostgresTranscriptSegments(pool=pool)
    records = PostgresVideoRecords(pool=pool)
    plans = []
    for video_id in segments_store.video_ids_with_glued_cues():
        record = records.get_by_id(video_id)
        if record is None:
            continue
        stored = segments_store.load(video_id)
        cues = [
            cue
            for segment in stored
            for cue in split_glued_cues(segment.text, segment.start_seconds, segment.end_seconds)
        ]
        repaired = normalize_caption_cues(
            cues,
            source=record.video.transcript_source or "captions",
            language=record.video.transcript_language,
        )
        if repaired is None:
            logger.warning("Video %s did not normalize once repaired; left as it is", video_id)
            continue
        plans.append(
            RepairPlan(
                video_id=video_id,
                title=record.video.title,
                stored_segment_count=len(stored),
                glued_segment_count=sum(1 for segment in stored if GLUED_TIMING_PATTERN.search(segment.text)),
                repaired=repaired,
            )
        )
    return plans


def apply_repair(plan: RepairPlan, *, pool=None) -> tuple[str, ...]:
    """Store the repaired transcript and run stages three to five on it; return their problems."""
    PostgresTranscriptSegments(pool=pool).replace(plan.video_id, plan.repaired.segments)
    segmented = segment_and_store(plan.video_id, plan.repaired, pool=pool)
    problems = list(segmented.problems)
    if segmented.memory_count:
        problems.extend(embed_video(plan.video_id, pool=pool).problems)
        problems.extend(generate_and_store_insights(plan.video_id, pool=pool).problems)
    return tuple(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the repair; without it, only report")
    arguments = parser.parse_args(argv)

    plans = plan_repairs()
    for plan in plans:
        logger.info(
            "%s (%s): %d stored segments, %d with a glued cue, %d once repaired",
            plan.video_id,
            plan.title,
            plan.stored_segment_count,
            plan.glued_segment_count,
            plan.repaired.segment_count,
        )
    if not arguments.apply:
        logger.info("%d videos to repair; nothing written. Run again with --apply to repair them.", len(plans))
        return 0

    failed = 0
    for plan in plans:
        problems = apply_repair(plan)
        if problems:
            failed += 1
            logger.error("Repairing video %s left problems: %s", plan.video_id, ", ".join(problems))
        else:
            logger.info("Repaired video %s", plan.video_id)
    logger.info("Repaired %d videos, %d with problems", len(plans) - failed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
