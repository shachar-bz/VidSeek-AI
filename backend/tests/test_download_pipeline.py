"""Tests for the order the five stages run in, and which failures cost a run its result.

Every stage is stood in for. What is under test is the pipeline's own judgment: what stops
a run, what only marks it, and what each stage is handed by the one before it.
"""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from yt_dlp.utils import DownloadCancelled

from backend.download_pipeline.embedding import EmbeddedVideo
from backend.download_pipeline.insights import InsightGenerationOutcome
from backend.download_pipeline.pipeline import run_download_pipeline
from backend.download_pipeline.result import (
    EMBEDDING_FAILED,
    INSIGHT_GENERATION_FAILED,
    RECORD_FAILED,
    SEGMENTATION_FAILED,
    VideoStorageError,
)
from backend.download_pipeline.segmentation import SegmentedVideo
from backend.download_pipeline.video_storage import StorageOutcome
from backend.schemas.video_jobs import CreateVideoJobRequest, JobPhase
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    TranscriptSegment,
)
from backend.services.video_download.web.pipeline import (
    UNTIMED_TRANSCRIPT_ERROR,
    PipelineResult,
)
from backend.storage.blob import StoredVideo

ACQUIRE_PATH = "backend.download_pipeline.pipeline.acquire_video"
STORE_PATH = "backend.download_pipeline.pipeline.store_video"
SEGMENT_PATH = "backend.download_pipeline.pipeline.segment_and_store"
EMBED_PATH = "backend.download_pipeline.pipeline.embed_video"
INSIGHTS_PATH = "backend.download_pipeline.pipeline.generate_and_store_insights"

VIDEO_ID = "11111111-2222-3333-4444-555555555555"

STORED = StoredVideo(
    container="videos", name="videos/job-42/video.mp4", size_bytes=5, content_type="video/mp4"
)

TRANSCRIPT = NormalizedTranscript(
    source="captions",
    timing_fidelity=TimingFidelity.CAPTION,
    segments=[TranscriptSegment(index=0, start_seconds=0.0, end_seconds=1.0, text="hello")],
)

REQUEST = CreateVideoJobRequest(page_url="https://example.com/watch", page_title="Example")


def _acquired(*, transcript=TRANSCRIPT, transcript_error=None) -> PipelineResult:
    return PipelineResult(
        video_path=Path("video.mp4"),
        transcript_text_path=Path("video.transcript.txt"),
        transcript_json_path=Path("video.transcript.json"),
        transcript_source="captions",
        transcript_error=transcript_error,
        normalized_transcript=transcript,
    )


def _run(
    *,
    acquired=None,
    storage=None,
    segmented=SegmentedVideo(memory_count=4, chapter_count=2),
    embedded=EmbeddedVideo(memory_count=4, chapter_count=2),
    insights=InsightGenerationOutcome(stored=True),
    cancel_event=None,
):
    """Run the pipeline with every stage stood in for, and report what each was called with."""
    from backend.download_pipeline import AcquisitionRoute

    storage = storage or StorageOutcome(stored_video=STORED, video_id=VIDEO_ID)
    calls: list[str] = []

    def record(name, value):
        def stage(*args, **kwargs):
            calls.append(name)
            if isinstance(value, Exception):
                raise value
            return value(*args, **kwargs) if callable(value) else value

        return stage

    with (
        patch(ACQUIRE_PATH, side_effect=record("acquire", acquired or _acquired())),
        patch(STORE_PATH, side_effect=record("store", storage)),
        patch(SEGMENT_PATH, side_effect=record("segment", segmented)) as segment_mock,
        patch(EMBED_PATH, side_effect=record("embed", embedded)) as embed_mock,
        patch(INSIGHTS_PATH, side_effect=record("insights", insights)) as insights_mock,
    ):
        processed = run_download_pipeline(
            AcquisitionRoute.COMPANION_DOWNLOAD,
            request=REQUEST,
            download_root=Path("."),
            job_id="job-42",
            acquisition_mode="companion_download",
            cancel_event=cancel_event or threading.Event(),
            progress_callback=lambda *_: None,
        )
    return processed, calls, segment_mock, embed_mock, insights_mock


def test_a_complete_run_walks_the_five_stages_in_order() -> None:
    processed, calls, _, _, _ = _run()

    assert calls == ["acquire", "store", "segment", "embed", "insights"]
    assert processed.video_id == VIDEO_ID
    assert processed.memory_count == 4
    assert processed.chapter_count == 2
    assert processed.memory_embedding_count == 4
    assert processed.problems == ()
    assert processed.is_searchable is True


def test_the_segmentation_stage_is_handed_the_transcript_the_download_produced() -> None:
    # Not re-read from the `.json` the download wrote beside the video: the segments are
    # already in hand, and reading them back would be a second chance to read them
    # differently.
    _, _, segment_mock, _, _ = _run()

    assert segment_mock.call_args[0] == (VIDEO_ID, TRANSCRIPT)


def test_a_video_blob_storage_would_not_take_stops_the_run() -> None:
    # Blob Storage is the video's only home, so there is nothing left to describe, divide
    # or embed once the upload has failed.
    with pytest.raises(VideoStorageError):
        _run(storage=VideoStorageError("container unreachable"))


def test_a_video_with_no_row_is_stored_but_not_indexed() -> None:
    # Memories, chapters and vectors are all keyed on the `videos` row, so without one
    # there is nowhere to put any of them.
    processed, calls, _, _, _ = _run(
        storage=StorageOutcome(stored_video=STORED, video_id=None, problem=RECORD_FAILED)
    )

    assert calls == ["acquire", "store"]
    assert processed.problems == (RECORD_FAILED,)
    assert processed.memory_count == 0


def test_a_checkout_with_no_database_finishes_without_reporting_a_problem() -> None:
    # `record_job_video` returns None when no database is configured, which is an expected
    # way to run rather than something wrong with the video.
    processed, calls, _, _, _ = _run(
        storage=StorageOutcome(stored_video=STORED, video_id=None)
    )

    assert calls == ["acquire", "store"]
    assert processed.problems == ()


def test_an_untimed_transcript_is_not_reported_twice() -> None:
    # The download stage already set `transcript_error`, and the job carries that; naming
    # the same fact again under a pipeline code would make one problem look like two.
    processed, calls, _, _, _ = _run(
        acquired=_acquired(transcript=None, transcript_error=UNTIMED_TRANSCRIPT_ERROR)
    )

    assert calls == ["acquire", "store"]
    assert processed.problems == ()
    assert processed.acquired.transcript_error == UNTIMED_TRANSCRIPT_ERROR


def test_a_transcript_that_could_not_be_divided_is_never_sent_to_be_embedded() -> None:
    processed, calls, _, _, _ = _run(
        segmented=SegmentedVideo(problems=(SEGMENTATION_FAILED,))
    )

    assert calls == ["acquire", "store", "segment"]
    assert processed.problems == (SEGMENTATION_FAILED,)


def test_a_video_that_could_not_be_embedded_still_keeps_its_memories() -> None:
    processed, calls, _, _, _ = _run(embedded=EmbeddedVideo(problems=(EMBEDDING_FAILED,)))

    assert calls == ["acquire", "store", "segment", "embed", "insights"]
    assert processed.memory_count == 4
    assert processed.problems == (EMBEDDING_FAILED,)
    assert processed.is_searchable is False


def test_problems_arrive_in_the_order_the_stages_hit_them() -> None:
    processed, _, _, _, _ = _run(
        storage=StorageOutcome(stored_video=STORED, video_id=VIDEO_ID, problem=RECORD_FAILED),
        embedded=EmbeddedVideo(problems=(EMBEDDING_FAILED,)),
    )

    assert processed.problems == (RECORD_FAILED, EMBEDDING_FAILED)


def test_a_run_cancelled_before_the_video_is_stored_has_no_result() -> None:
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(DownloadCancelled):
        _run(cancel_event=cancelled)


def test_a_run_cancelled_after_the_video_is_stored_keeps_it_and_skips_the_model_stages() -> None:
    # The video is in Blob Storage whatever anyone now wants, so reporting the run as
    # cancelled would be untrue -- and spending minutes of model time on a video somebody
    # asked to stop would be worse. The cancel is honoured by stopping, not by unwinding.
    cancelled = threading.Event()

    def cancel_once_stored(*_args, **_kwargs):
        cancelled.set()
        return StorageOutcome(stored_video=STORED, video_id=VIDEO_ID)

    processed, calls, _, _, _ = _run(storage=cancel_once_stored, cancel_event=cancelled)

    assert calls == ["acquire", "store"]
    assert processed.video_id == VIDEO_ID
    assert processed.problems == ()


def test_insight_failure_keeps_all_earlier_artifacts() -> None:
    processed, calls, _, _, _ = _run(
        insights=InsightGenerationOutcome(problems=(INSIGHT_GENERATION_FAILED,))
    )

    assert calls == ["acquire", "store", "segment", "embed", "insights"]
    assert processed.memory_count == 4
    assert processed.chapter_count == 2
    assert processed.memory_embedding_count == 4
    assert processed.chapter_embedding_count == 2
    assert processed.problems == (INSIGHT_GENERATION_FAILED,)


def test_insights_publish_the_final_processing_phase_after_embedding() -> None:
    from backend.download_pipeline import AcquisitionRoute

    progress = []
    with (
        patch(ACQUIRE_PATH, return_value=_acquired()),
        patch(STORE_PATH, return_value=StorageOutcome(stored_video=STORED, video_id=VIDEO_ID)),
        patch(SEGMENT_PATH, return_value=SegmentedVideo(memory_count=4, chapter_count=2)),
        patch(EMBED_PATH, return_value=EmbeddedVideo(memory_count=4, chapter_count=2)),
        patch(INSIGHTS_PATH, return_value=InsightGenerationOutcome(stored=True)),
    ):
        run_download_pipeline(
            AcquisitionRoute.COMPANION_DOWNLOAD,
            request=REQUEST,
            download_root=Path("."),
            job_id="job-42",
            acquisition_mode="companion_download",
            cancel_event=threading.Event(),
            progress_callback=lambda phase, value, message: progress.append(
                (phase, value, message)
            ),
        )

    assert [phase for phase, _, _ in progress] == [
        JobPhase.SEGMENTATION,
        JobPhase.EMBEDDING,
        JobPhase.INSIGHTS,
    ]
    assert progress[-1] == (JobPhase.INSIGHTS, 0.99, "Generating video insights")


COMMENT_EMBED_PATH = "backend.download_pipeline.pipeline.embed_comments"


def _acquired_with_comments(comments, *, transcript=TRANSCRIPT) -> PipelineResult:
    from dataclasses import replace

    return replace(_acquired(transcript=transcript), comments=comments)


def _a_comment():
    from backend.services.video_download.youtube.comments import CommentEntry

    return CommentEntry(
        id="c1", author="A", text="great", like_count=3, reply_count=0,
        published_at="2026-09-14T10:00:00+00:00",
    )


@pytest.mark.parametrize("comments", [None, ()])
def test_comments_are_embedded_only_when_this_run_fetched_some(comments) -> None:
    """None is a failed fetch, which keeps an earlier scan's vectors; empty already cleared them."""
    from backend.download_pipeline.embedding import EmbeddedComments

    with patch(COMMENT_EMBED_PATH, return_value=EmbeddedComments(comment_count=1)) as embed:
        processed, *_ = _run(acquired=_acquired_with_comments(comments))

    embed.assert_not_called()
    assert processed.comment_embedding_count == 0


def test_fetched_comments_are_embedded_even_when_there_is_no_transcript() -> None:
    from backend.download_pipeline.embedding import EmbeddedComments

    with patch(COMMENT_EMBED_PATH, return_value=EmbeddedComments(comment_count=1)) as embed:
        processed, calls, *_ = _run(
            acquired=_acquired_with_comments(
                (_a_comment(),), transcript=None
            )
        )

    embed.assert_called_once_with(VIDEO_ID, pool=None)
    assert processed.comment_embedding_count == 1
    assert calls == ["acquire", "store"]


def test_comments_that_could_not_be_embedded_are_a_problem_not_a_failure() -> None:
    from backend.download_pipeline.embedding import EmbeddedComments
    from backend.download_pipeline.result import COMMENT_EMBEDDING_FAILED

    failed = EmbeddedComments(problems=(COMMENT_EMBEDDING_FAILED,))
    with patch(COMMENT_EMBED_PATH, return_value=failed):
        processed, calls, *_ = _run(acquired=_acquired_with_comments((_a_comment(),)))

    assert processed.problems == (COMMENT_EMBEDDING_FAILED,)
    assert calls == ["acquire", "store", "segment", "embed", "insights"]
