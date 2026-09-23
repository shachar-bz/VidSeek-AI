"""Tests for the database row a finished job writes once its video is in the container."""

from unittest.mock import patch

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    TranscriptSegment,
)
from backend.services.video_download import video_record
from backend.services.video_download.youtube.comments import CommentEntry
from backend.storage.blob import StoredVideo
from backend.storage.postgres import StoredVideoRecord, VideoRecord

VIDEO_ROW_ID = "11111111-2222-3333-4444-555555555555"

STORED = StoredVideo(
    container="videos",
    name="videos/job-42/clip.mp4",
    size_bytes=11,
    content_type="video/mp4",
)

REQUEST = CreateVideoJobRequest(
    page_url="https://example.com/lecture",
    page_title="Lecture 3",
)

TRANSCRIPT = NormalizedTranscript(
    source="elevenlabs",
    timing_fidelity=TimingFidelity.WORD,
    language="he",
    segments=[
        TranscriptSegment(index=0, start_seconds=0.0, end_seconds=1.5, text="שלום"),
        TranscriptSegment(index=1, start_seconds=1.5, end_seconds=3.0, text="and welcome"),
    ],
)

COMMENTS = [
    CommentEntry(
        id="comment-1",
        author="A Viewer",
        text="great video",
        like_count=5,
        reply_count=1,
        published_at="2026-09-14T10:00:00+00:00",
    ),
]


class FakeVideoRecords:
    """Stands in for the `videos` table, answering with the row it wrote."""

    def __init__(self):
        self.upserted: list[VideoRecord] = []

    def upsert(self, record: VideoRecord) -> StoredVideoRecord:
        self.upserted.append(record)
        return StoredVideoRecord(
            id=VIDEO_ROW_ID,
            created_at="2026-09-14T10:00:00+00:00",
            updated_at="2026-09-14T10:00:00+00:00",
            video=record,
        )


class FakeTranscriptSegments:
    """Stands in for the `transcript_segments` table."""

    def __init__(self):
        self.replaced: list[tuple[str, list[TranscriptSegment]]] = []

    def replace(self, video_id: str, segments) -> int:
        self.replaced.append((video_id, list(segments)))
        return len(self.replaced[-1][1])


class FakeVideoComments:
    """Stands in for the `video_comments` table."""

    def __init__(self):
        self.replaced: list[tuple[str, list[CommentEntry]]] = []

    def replace(self, video_id: str, comments) -> int:
        self.replaced.append((video_id, list(comments)))
        return len(self.replaced[-1][1])


class FakeUserVideos:
    """Stands in for the `user_videos` table."""

    def __init__(self):
        self.linked: list[tuple[str, str]] = []

    def link(self, user_id: str, video_id: str):
        self.linked.append((user_id, video_id))


def _record(
    records: FakeVideoRecords,
    segments: FakeTranscriptSegments | None = None,
    comments_store: FakeVideoComments | None = None,
    user_videos: FakeUserVideos | None = None,
    *,
    configured: bool = True,
    transcript: NormalizedTranscript | None = None,
    comments: list[CommentEntry] | None = None,
    user_id: str | None = None,
    duration_seconds: float | None = None,
    reported_title: str | None = None,
):
    with (
        patch.object(video_record, "is_postgres_configured", return_value=configured),
        patch.object(video_record, "PostgresVideoRecords", return_value=records),
        patch.object(
            video_record,
            "PostgresTranscriptSegments",
            return_value=segments or FakeTranscriptSegments(),
        ),
        patch.object(
            video_record,
            "PostgresComments",
            return_value=comments_store or FakeVideoComments(),
        ),
        patch.object(
            video_record,
            "PostgresUserVideos",
            return_value=user_videos or FakeUserVideos(),
        ),
    ):
        return video_record.record_job_video(
            stored_video=STORED,
            request=REQUEST,
            job_id="job-42",
            acquisition_mode="companion_download",
            transcript_source="page_transcript",
            transcript=transcript,
            comments=comments,
            user_id=user_id,
            duration_seconds=duration_seconds,
            reported_title=reported_title,
        )


def test_the_row_ties_the_stored_blob_back_to_the_page_it_came_from() -> None:
    records = FakeVideoRecords()
    stored = _record(records)

    written = records.upserted[0]
    assert written.blob_container == STORED.container
    assert written.blob_name == STORED.name
    assert written.source_url == REQUEST.page_url
    assert written.title == REQUEST.page_title
    assert written.source == "companion_download"
    assert written.transcript_source == "page_transcript"
    assert written.job_id == "job-42"
    assert stored is not None and stored.video == written


def test_the_platform_s_own_title_is_kept_over_the_tab_title() -> None:
    records = FakeVideoRecords()
    _record(records, reported_title="Lecture 3: Recursion")

    assert records.upserted[0].title == "Lecture 3: Recursion"


def test_the_video_is_linked_into_the_account_that_started_the_job() -> None:
    records, user_videos = FakeVideoRecords(), FakeUserVideos()
    _record(records, user_videos=user_videos, user_id="11111111-2222-3333-4444-555555555555")

    assert user_videos.linked == [("11111111-2222-3333-4444-555555555555", VIDEO_ROW_ID)]


def test_a_job_with_no_signed_in_account_links_nobody() -> None:
    records, user_videos = FakeVideoRecords(), FakeUserVideos()
    _record(records, user_videos=user_videos)

    assert user_videos.linked == []


def test_the_uploaded_blob_s_own_facts_are_taken_from_the_upload() -> None:
    # The size and content type belong to the file that was actually stored, not to
    # anything the tab claimed about it.
    records = FakeVideoRecords()
    _record(records)

    assert records.upserted[0].file_size_bytes == STORED.size_bytes
    assert records.upserted[0].content_type == STORED.content_type


def test_nothing_is_guessed_for_what_no_pipeline_measured() -> None:
    # An id parsed out of a URL would put something in the table that nobody measured.
    # Null says the same thing honestly. Duration is not guessed either, but is written
    # when a caller actually measured one -- see the tests below.
    records = FakeVideoRecords()
    _record(records)

    assert records.upserted[0].duration_seconds is None
    assert records.upserted[0].source_video_id is None


def test_a_measured_duration_is_recorded_on_the_video_row() -> None:
    records = FakeVideoRecords()
    _record(records, duration_seconds=754.2)

    assert records.upserted[0].duration_seconds == 754.2


def test_an_unmeasurable_duration_still_records_the_video() -> None:
    # ffprobe not finding a duration is not a reason to lose an otherwise usable video.
    records = FakeVideoRecords()
    stored = _record(records, duration_seconds=None)

    assert stored is not None
    assert records.upserted[0].duration_seconds is None


def test_the_transcript_is_stored_against_the_video_row_the_upsert_returned() -> None:
    # The segments carry a foreign key to `videos.id`, which only exists once the video
    # row has been written; the blob name that identified the video up to here will not do.
    records, segments = FakeVideoRecords(), FakeTranscriptSegments()
    _record(records, segments, transcript=TRANSCRIPT)

    assert segments.replaced == [(VIDEO_ROW_ID, TRANSCRIPT.segments)]


def test_what_is_true_of_the_whole_transcript_goes_on_the_video_row() -> None:
    # Repeating the source, language and fidelity on every segment would say the same
    # thing a few thousand times and leave room for the copies to disagree.
    records = FakeVideoRecords()
    _record(records, transcript=TRANSCRIPT)

    assert records.upserted[0].transcript_language == "he"
    assert records.upserted[0].transcript_timing_fidelity == "word"


def test_a_job_that_produced_no_timed_transcript_records_the_video_alone() -> None:
    records, segments = FakeVideoRecords(), FakeTranscriptSegments()
    stored = _record(records, segments, transcript=None)

    assert stored is not None
    assert segments.replaced == []
    assert records.upserted[0].transcript_timing_fidelity is None


def test_without_a_project_the_video_stays_unrecorded_rather_than_the_job_failing() -> None:
    records, segments = FakeVideoRecords(), FakeTranscriptSegments()
    stored = _record(records, segments, configured=False)

    assert stored is None
    assert records.upserted == []
    assert segments.replaced == []


def test_comments_are_stored_against_the_video_row_the_upsert_returned() -> None:
    # Same reasoning as the transcript: comments carry a foreign key to `videos.id`, which
    # only exists once the video row has been written.
    records, comments_store = FakeVideoRecords(), FakeVideoComments()
    _record(records, comments_store=comments_store, comments=COMMENTS)

    assert comments_store.replaced == [(VIDEO_ROW_ID, COMMENTS)]


def test_no_comments_argument_means_nothing_is_written_for_a_non_youtube_video() -> None:
    # Only the YouTube pipeline ever fetches comments; every other pipeline leaves the
    # argument unset, and that should leave the table alone rather than clearing it.
    records, comments_store = FakeVideoRecords(), FakeVideoComments()
    _record(records, comments_store=comments_store)

    assert comments_store.replaced == []


def test_an_empty_comments_list_still_clears_out_a_previous_fetch() -> None:
    # Comments disabled, or none found, is a real answer from the YouTube pipeline and
    # distinct from never having asked -- it should overwrite whatever was stored before.
    records, comments_store = FakeVideoRecords(), FakeVideoComments()
    _record(records, comments_store=comments_store, comments=[])

    assert comments_store.replaced == [(VIDEO_ROW_ID, [])]
