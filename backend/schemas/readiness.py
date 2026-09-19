"""How far along a video is, and the one rule that decides it.

The website shows a stage rather than a percentage, and it shows the same stage in two
places -- a row on the library page and the header of a video page -- which are served by
two different endpoints reading two different queries. Deriving the stage separately in each
would be two chances to disagree about whether chat is available, so the rule lives here
once and both call it.

A stage is a statement about what *exists*, never a prediction. `understanding` means the
player and the transcript work and the chapters do not exist yet; it says nothing about
whether they ever will. A job that finished with `segmentation_failed` therefore sits at
`understanding` permanently, which is the truth about that video -- the browsable half works
and the rest never arrived -- and the job's own message is what explains why it stopped.

Chat is gated on fully processed results: both `ready` and `partial`. Retrieval is tools-only,
and every retrieval tool but `get_video_info` reads memories, chapters or embeddings, so a
video that is still processing has nothing for the agent to find. `partial` differs only in
timestamp reliability, not capability. `ReadinessStage.allows_chat` keeps that rule beside
the stages rather than restating it at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .video_jobs import JobPhase, JobStatus

# The phases that happen before a transcript exists, and the ones that happen after the
# video is browsable. `JobPhase.UPLOAD` counts as transcribing rather than as its own stage:
# the spec's `transcribing` covers a blob "being produced or uploaded", and the website has
# nothing to offer during either.
PHASES_BEFORE_A_TRANSCRIPT = frozenset(
    {JobPhase.DOWNLOAD, JobPhase.TRANSCRIPT_LOOKUP, JobPhase.TRANSCRIPTION, JobPhase.UPLOAD}
)

# The pipeline's name for a transcript that has text but no usable timings. It is the one
# problem code that changes the stage rather than merely explaining it, because it is the
# one the website has to keep working around: click-to-seek and every timestamp the agent
# produces are unreliable on such a video, and `partial` is what says so.
UNTIMED_TRANSCRIPT_ERROR = "untimed_transcript"

# Problem codes that leave nothing browsable behind. `transcription_failed` keeps the video
# but never produced text, and `record_failed` leaves the blob in the container with no row
# to hang a transcript, chapters or a library link off; a page can show neither.
PROBLEMS_WITH_NOTHING_TO_SHOW = frozenset({"transcription_failed", "record_failed"})


class ReadinessStage(str, Enum):
    """The six states a video is shown in, from §1.3 of the website specification.

    The first four are a sequence and the last two are terminal states outside it. There is
    deliberately no seventh for a cancelled job: a cancel that produced no usable video is
    reported as `FAILED`, with the job's own message saying it was cancelled, rather than
    adding a state every consumer would have to learn in order to treat it the same way.
    """

    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    READY = "ready"
    FAILED = "failed"
    PARTIAL = "partial"

    @property
    def allows_chat(self) -> bool:
        """Whether the agent has anything to retrieve from this video.

        True for `READY`, and for `PARTIAL` -- an untimed transcript was still segmented,
        embedded and grouped into chapters, so every tool answers; only the timestamps in
        those answers are unreliable, which is a caveat the page shows rather than a reason
        to withhold the feature.
        """
        return self in {ReadinessStage.READY, ReadinessStage.PARTIAL}

    @property
    def allows_browsing(self) -> bool:
        """Whether the player and the transcript are worth putting on the page."""
        return self in {
            ReadinessStage.UNDERSTANDING,
            ReadinessStage.READY,
            ReadinessStage.PARTIAL,
        }


@dataclass(frozen=True)
class VideoArtifacts:
    """What a video actually has in the database, as one row of yes-or-no answers.

    Booleans rather than the rows themselves because the library page derives a stage for
    every video it lists, and reading each video's chapters, vectors and insights to decide
    how to label a row would make listing a library cost as much as opening every video in
    it. A caller is expected to answer all six in one aggregate query.

    `has_timed_transcript` is false only for the pipeline's `untimed_transcript` outcome: a
    transcript whose lines carry no usable timing. It is what separates `PARTIAL` from
    `READY`, and it is read off the job's error code or the video's own
    `transcript_timing_fidelity`, whichever the caller has.
    """

    has_video_row: bool = False
    has_transcript: bool = False
    has_timed_transcript: bool = False
    has_chapters: bool = False
    has_embeddings: bool = False
    has_insights: bool = False


def derive_readiness_stage(
    artifacts: VideoArtifacts,
    *,
    job_status: JobStatus | None = None,
    job_phase: JobPhase | None = None,
    job_error_code: str | None = None,
) -> ReadinessStage:
    """The stage one video is shown in, from its job and from what it has produced.

    The job is consulted first and only while it is still running, because a job in flight
    is the only source of truth about a video that does not exist yet. Once the job reaches
    a terminal state -- or when there is no job at all, which is every video recorded before
    `video_jobs` existed and every video whose job row has been pruned -- the stage is read
    entirely off what the video has, so that a video does not regress or get stuck because
    its job row was lost.
    """
    running_stage = _stage_while_running(job_status, job_phase)
    if running_stage is not None:
        return running_stage

    if job_error_code in PROBLEMS_WITH_NOTHING_TO_SHOW:
        return ReadinessStage.FAILED
    if job_status in {JobStatus.FAILED, JobStatus.CANCELLED} and not artifacts.has_transcript:
        return ReadinessStage.FAILED

    return _stage_from_artifacts(artifacts, job_error_code=job_error_code)


def _stage_while_running(
    job_status: JobStatus | None, job_phase: JobPhase | None
) -> ReadinessStage | None:
    """The stage a job still in flight puts its video in, or None once it is terminal.

    A queued job and one waiting for Chrome to finish a download are both `DOWNLOADING`:
    from the library's point of view nothing has happened yet, and distinguishing "waiting
    for a worker" from "waiting for a browser" is the extension's business.
    """
    if job_status is None or job_status not in {
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.AWAITING_BROWSER_DOWNLOAD,
    }:
        return None
    if job_phase is None or job_phase == JobPhase.DOWNLOAD:
        return ReadinessStage.DOWNLOADING
    if job_phase in PHASES_BEFORE_A_TRANSCRIPT:
        return ReadinessStage.TRANSCRIBING
    return ReadinessStage.UNDERSTANDING


def _stage_from_artifacts(
    artifacts: VideoArtifacts, *, job_error_code: str | None
) -> ReadinessStage:
    """The stage a video's own contents put it in, with no running job to consult."""
    if not artifacts.has_video_row:
        return ReadinessStage.FAILED
    if not artifacts.has_transcript:
        # The blob may well exist, but a video with no transcript is not browsable: §1.3
        # gives the player and the transcript to `understanding` together.
        return ReadinessStage.FAILED
    if not (artifacts.has_chapters and artifacts.has_embeddings and artifacts.has_insights):
        return ReadinessStage.UNDERSTANDING
    if job_error_code == UNTIMED_TRANSCRIPT_ERROR or not artifacts.has_timed_transcript:
        return ReadinessStage.PARTIAL
    return ReadinessStage.READY
