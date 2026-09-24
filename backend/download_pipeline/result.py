"""What one run of the pipeline produced, and the names for what it could not.

A run has two kinds of failure and they are not represented the same way. A stage the
video cannot exist without — acquiring it, and putting it somewhere durable — raises, and
the run has no result. Every stage after that describes the video rather than being the
video, so a failure there is recorded on the result as a problem code and the run finishes
with everything the earlier stages did produce. That is the whole reason this type carries
a `problems` tuple instead of the pipeline raising on the first thing that goes wrong: a
video whose chapters could not be grouped is still a downloaded, stored, transcribed video,
and throwing that away to report the grouping would be the worse trade.

The codes are strings rather than an enum because they leave this process: the job manager
puts one in `VideoJobResponse.error_code`, which the extension displays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.video_download.web.pipeline import PipelineResult
from backend.storage.blob import StoredVideo

# The video is in Blob Storage but no row in `videos` describes it. Recoverable later from
# the blob name alone, which is why it costs the run a problem code rather than its result.
RECORD_FAILED = "record_failed"

# The transcript could not be divided into memories, so there is nothing for the chapter
# and embedding stages to work from either.
SEGMENTATION_FAILED = "segmentation_failed"

# Memories were produced and stored, but grouping them into chapters failed. The memories
# are kept ungrouped, which is the state every memory is in between the two stages anyway.
CHAPTER_GROUPING_FAILED = "chapter_grouping_failed"

# Memories or chapters are stored but have no vectors, so the video is not searchable yet.
# Re-runnable on its own: both embedding pipelines read from the database rather than from
# anything this run still holds.
EMBEDDING_FAILED = "embedding_failed"

# The video's durable chapters and memories remain available, but the summary, takeaways
# and suggested questions could not be generated or stored.
INSIGHT_GENERATION_FAILED = "insight_generation_failed"


class VideoStorageError(RuntimeError):
    """Blob Storage would not take the video, which costs the run its result.

    Distinct from every other failure in the pipeline because Blob Storage is the video's
    only home: the local copy exists to get the video transcribed and indexed and is deleted
    afterwards, so a video that never reached the container has nowhere left to live. Raised in place of
    whatever the storage client raised, which stays reachable as `__cause__`.
    """


@dataclass(frozen=True)
class ProcessedVideo:
    """One video carried as far through the pipeline as this run could take it.

    `acquired` is the download stage's own result, passed through untouched: it holds the
    local artifact paths, the transcript source and the normalized transcript, and the job
    manager reports all three to the extension. Everything else here is what the stages
    after it added.
    """

    acquired: PipelineResult
    stored_video: StoredVideo

    # The `videos` row's id, or None when no database is configured. None is what makes
    # every later count zero: memories, chapters and vectors all hang off this row.
    video_id: str | None = None

    memory_count: int = 0
    chapter_count: int = 0
    memory_embedding_count: int = 0
    chapter_embedding_count: int = 0

    # In the order the stages hit them, so the first is the earliest thing that went wrong
    # and therefore the one most likely to explain the rest.
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_searchable(self) -> bool:
        """Whether this video came out of the pipeline with vectors to search."""
        return self.memory_embedding_count > 0
