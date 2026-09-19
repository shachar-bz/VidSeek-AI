"""Tests for the rule that decides which stage a video is shown in."""

import pytest

from backend.schemas.readiness import (
    UNTIMED_TRANSCRIPT_ERROR,
    ReadinessStage,
    VideoArtifacts,
    derive_readiness_stage,
)
from backend.schemas.video_jobs import JobPhase, JobStatus

NOTHING = VideoArtifacts()

BROWSABLE = VideoArtifacts(has_video_row=True, has_transcript=True, has_timed_transcript=True)

EVERYTHING = VideoArtifacts(
    has_video_row=True,
    has_transcript=True,
    has_timed_transcript=True,
    has_chapters=True,
    has_embeddings=True,
    has_insights=True,
)


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (JobPhase.DOWNLOAD, ReadinessStage.DOWNLOADING),
        (JobPhase.TRANSCRIPT_LOOKUP, ReadinessStage.TRANSCRIBING),
        (JobPhase.TRANSCRIPTION, ReadinessStage.TRANSCRIBING),
        (JobPhase.UPLOAD, ReadinessStage.TRANSCRIBING),
        (JobPhase.SEGMENTATION, ReadinessStage.UNDERSTANDING),
        (JobPhase.EMBEDDING, ReadinessStage.UNDERSTANDING),
        (JobPhase.INSIGHTS, ReadinessStage.UNDERSTANDING),
    ],
)
def test_a_running_job_is_staged_by_its_phase(phase: JobPhase, expected: ReadinessStage) -> None:
    stage = derive_readiness_stage(NOTHING, job_status=JobStatus.RUNNING, job_phase=phase)

    assert stage == expected


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.AWAITING_BROWSER_DOWNLOAD, JobStatus.RUNNING]
)
def test_a_job_that_has_not_started_working_is_downloading(status: JobStatus) -> None:
    # From the library's point of view nothing has happened yet, and whether the wait is for
    # a worker or for Chrome is the extension's business rather than the page's.
    stage = derive_readiness_stage(NOTHING, job_status=status, job_phase=JobPhase.DOWNLOAD)

    assert stage == ReadinessStage.DOWNLOADING


def test_a_finished_job_is_staged_by_what_the_video_has_rather_than_by_its_phase() -> None:
    # `JobPhase.COMPLETE` is set on a failure as well as on a success, so the phase cannot
    # be what decides a terminal job.
    stage = derive_readiness_stage(
        EVERYTHING, job_status=JobStatus.COMPLETE, job_phase=JobPhase.COMPLETE
    )

    assert stage == ReadinessStage.READY


def test_a_video_with_no_job_row_is_still_staged_by_what_it_has() -> None:
    # Every video recorded before jobs were persisted, and every video whose job row has
    # been pruned. It must not regress to `downloading` because its job is gone.
    assert derive_readiness_stage(EVERYTHING) == ReadinessStage.READY


def test_a_browsable_video_without_chapters_stays_at_understanding() -> None:
    assert derive_readiness_stage(BROWSABLE) == ReadinessStage.UNDERSTANDING


@pytest.mark.parametrize(
    "missing", ["has_chapters", "has_embeddings", "has_insights"]
)
def test_ready_needs_chapters_embeddings_and_insights_together(missing: str) -> None:
    # Chat is gated on `ready`, and every retrieval tool but `get_video_info` reads one of
    # these; a video missing any of them has nothing for the agent to find.
    artifacts = VideoArtifacts(**{**vars(EVERYTHING), missing: False})

    assert derive_readiness_stage(artifacts) == ReadinessStage.UNDERSTANDING


def test_a_fully_processed_video_whose_transcript_was_never_timed_is_partial() -> None:
    untimed = VideoArtifacts(**{**vars(EVERYTHING), "has_timed_transcript": False})

    assert derive_readiness_stage(untimed) == ReadinessStage.PARTIAL


def test_the_untimed_transcript_problem_code_alone_makes_a_video_partial() -> None:
    stage = derive_readiness_stage(
        EVERYTHING, job_status=JobStatus.PARTIAL_SUCCESS, job_error_code=UNTIMED_TRANSCRIPT_ERROR
    )

    assert stage == ReadinessStage.PARTIAL


@pytest.mark.parametrize("code", ["transcription_failed", "record_failed"])
def test_a_job_that_left_nothing_browsable_is_failed(code: str) -> None:
    stage = derive_readiness_stage(
        BROWSABLE, job_status=JobStatus.PARTIAL_SUCCESS, job_error_code=code
    )

    assert stage == ReadinessStage.FAILED


@pytest.mark.parametrize(
    "code",
    [
        "segmentation_failed",
        "chapter_grouping_failed",
        "embedding_failed",
        "insight_generation_failed",
    ],
)
def test_a_job_that_stopped_after_the_transcript_leaves_a_browsable_video(code: str) -> None:
    # The player and the transcript work and the chapters never arrived. `understanding` is
    # the truth about that video; the job's own message is what explains that it stopped.
    stage = derive_readiness_stage(
        BROWSABLE, job_status=JobStatus.PARTIAL_SUCCESS, job_error_code=code
    )

    assert stage == ReadinessStage.UNDERSTANDING


def test_a_failed_job_that_produced_nothing_is_failed() -> None:
    stage = derive_readiness_stage(
        NOTHING, job_status=JobStatus.FAILED, job_phase=JobPhase.DOWNLOAD
    )

    assert stage == ReadinessStage.FAILED


def test_a_cancelled_job_is_reported_as_failed_rather_than_as_a_seventh_stage() -> None:
    stage = derive_readiness_stage(NOTHING, job_status=JobStatus.CANCELLED)

    assert stage == ReadinessStage.FAILED


def test_a_video_with_no_transcript_is_failed_even_without_a_job_to_blame() -> None:
    # §1.3 gives the player and the transcript to `understanding` together, so a video with
    # a blob and no text has nothing to show.
    artifacts = VideoArtifacts(has_video_row=True)

    assert derive_readiness_stage(artifacts) == ReadinessStage.FAILED


@pytest.mark.parametrize(
    ("stage", "chat"),
    [
        (ReadinessStage.DOWNLOADING, False),
        (ReadinessStage.TRANSCRIBING, False),
        (ReadinessStage.UNDERSTANDING, False),
        (ReadinessStage.READY, True),
        (ReadinessStage.PARTIAL, True),
        (ReadinessStage.FAILED, False),
    ],
)
def test_chat_is_available_exactly_where_retrieval_has_something_to_find(
    stage: ReadinessStage, chat: bool
) -> None:
    assert stage.allows_chat is chat


@pytest.mark.parametrize(
    ("stage", "browsable"),
    [
        (ReadinessStage.DOWNLOADING, False),
        (ReadinessStage.TRANSCRIBING, False),
        (ReadinessStage.UNDERSTANDING, True),
        (ReadinessStage.READY, True),
        (ReadinessStage.PARTIAL, True),
        (ReadinessStage.FAILED, False),
    ],
)
def test_the_player_and_transcript_appear_exactly_where_they_exist(
    stage: ReadinessStage, browsable: bool
) -> None:
    assert stage.allows_browsing is browsable
