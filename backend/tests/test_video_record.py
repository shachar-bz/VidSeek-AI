"""Tests for the Supabase row a finished job writes once its video is in the bucket."""

from unittest.mock import patch

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.transcripts import (
    NormalizedTranscript,
    TimingFidelity,
    TranscriptSegment,
)
from backend.services.video_download import video_record
from backend.storage.r2 import StoredVideo
from backend.storage.supabase import StoredVideoRecord, VideoRecord

VIDEO_ROW_ID = "11111111-2222-3333-4444-555555555555"

STORED = StoredVideo(
    bucket="vidseek-videos",
    key="videos/job-42/clip.mp4",
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


class FakeVideoRecords:
    """Stands in for the `videos` table, and answers the way PostgREST does."""

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


def _record(
    records: FakeVideoRecords,
    segments: FakeTranscriptSegments | None = None,
    *,
    configured: bool = True,
    transcript: NormalizedTranscript | None = None,
):
    with (
        patch.object(video_record, "is_supabase_configured", return_value=configured),
        patch.object(video_record, "SupabaseVideoRecords", return_value=records),
        patch.object(
            video_record,
            "SupabaseTranscriptSegments",
            return_value=segments or FakeTranscriptSegments(),
        ),
    ):
        return video_record.record_job_video(
            stored_video=STORED,
            request=REQUEST,
            job_id="job-42",
            acquisition_mode="companion_download",
            transcript_source="page_transcript",
            transcript=transcript,
        )


def test_the_row_ties_the_r2_object_back_to_the_page_it_came_from() -> None:
    records = FakeVideoRecords()
    stored = _record(records)

    written = records.upserted[0]
    assert written.r2_bucket == STORED.bucket
    assert written.r2_object_key == STORED.key
    assert written.source_url == REQUEST.page_url
    assert written.title == REQUEST.page_title
    assert written.source == "companion_download"
    assert written.transcript_source == "page_transcript"
    assert written.job_id == "job-42"
    assert stored is not None and stored.video == written


def test_the_uploaded_object_s_own_facts_are_taken_from_the_upload() -> None:
    # The size and content type belong to the file that was actually stored, not to
    # anything the tab claimed about it.
    records = FakeVideoRecords()
    _record(records)

    assert records.upserted[0].file_size_bytes == STORED.size_bytes
    assert records.upserted[0].content_type == STORED.content_type


def test_nothing_is_guessed_for_what_no_pipeline_measured() -> None:
    # A duration read off a filename, or an id parsed out of a URL, would put a number in
    # the table that nobody measured. Null says the same thing honestly.
    records = FakeVideoRecords()
    _record(records)

    assert records.upserted[0].duration_seconds is None
    assert records.upserted[0].source_video_id is None


def test_the_transcript_is_stored_against_the_video_row_the_upsert_returned() -> None:
    # The segments carry a foreign key to `videos.id`, which only exists once the video
    # row has been written; the R2 key that identified the video up to here will not do.
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
