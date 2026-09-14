"""Tests for the Supabase settings and the `videos` table the backend writes through."""

import pytest

from backend.storage.supabase import (
    StoredVideoRecord,
    SupabaseSettings,
    SupabaseVideoRecords,
    VideoRecord,
    is_supabase_configured,
)
from backend.storage.supabase.settings import load_supabase_settings
from backend.storage.supabase.video_records import CONFLICT_TARGET, TABLE_NAME

SETTINGS = SupabaseSettings(
    url="https://project.supabase.co",
    api_key="service-role-key",
    uses_service_role=True,
)

RECORD = VideoRecord(
    source="youtube_pipeline",
    source_url="https://www.youtube.com/watch?v=abc",
    title="A Talk",
    r2_bucket="vidseek-videos",
    r2_object_key="videos/job-42/clip.mp4",
    file_size_bytes=11,
    content_type="video/mp4",
    transcript_source="youtube_captions",
    job_id="job-42",
)

ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
    **RECORD.to_row(),
}


class FakeTable:
    """Records the query that was built, and answers with whatever rows it was given."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple] = []

    def _record(self, *call):
        self.calls.append(call)
        return self

    def upsert(self, row, on_conflict=None):
        return self._record("upsert", row, on_conflict)

    def select(self, columns):
        return self._record("select", columns)

    def delete(self):
        return self._record("delete")

    def eq(self, column, value):
        return self._record("eq", column, value)

    def order(self, column, desc=False):
        return self._record("order", column, desc)

    def limit(self, count):
        return self._record("limit", count)

    def execute(self):
        return FakeResponse(self.rows)


class FakeResponse:
    def __init__(self, data: list[dict]):
        self.data = data


class FakeSupabaseClient:
    def __init__(self, rows: list[dict] | None = None):
        self.table_stub = FakeTable(rows if rows is not None else [])
        self.tables_touched: list[str] = []

    def table(self, name: str) -> FakeTable:
        self.tables_touched.append(name)
        return self.table_stub


def _records(rows: list[dict] | None = None) -> tuple[SupabaseVideoRecords, FakeSupabaseClient]:
    client = FakeSupabaseClient(rows)
    return SupabaseVideoRecords(client=client), client


def test_a_video_is_upserted_against_the_object_it_describes() -> None:
    records, client = _records([ROW])
    stored = records.upsert(RECORD)

    assert client.tables_touched == [TABLE_NAME]
    assert client.table_stub.calls[0] == ("upsert", RECORD.to_row(), CONFLICT_TARGET)
    assert stored.id == ROW["id"]
    assert stored.video == RECORD


def test_an_unset_field_is_written_as_null_rather_than_left_out() -> None:
    # The write is an upsert, so an omitted column keeps whatever an earlier run put
    # there: a video re-downloaded without a transcript would still claim the old source.
    records, client = _records([ROW])
    records.upsert(VideoRecord(**{**RECORD.to_row(), "transcript_source": None}))

    assert client.table_stub.calls[0][1]["transcript_source"] is None


def test_an_upsert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    # PostgREST answers with the row it wrote. An empty answer means the write did not
    # land -- row level security refusing the anon key looks exactly like this.
    records, _ = _records([])

    with pytest.raises(RuntimeError, match="returned no row"):
        records.upsert(RECORD)


def test_a_video_is_looked_up_by_bucket_as_well_as_key() -> None:
    # A key alone does not identify an object; the same key in another bucket is another
    # video, and this project has already changed its bucket layout once.
    records, client = _records([ROW])
    found = records.get_by_object_key("vidseek-videos", "videos/job-42/clip.mp4")

    assert found is not None and found.video == RECORD
    assert ("eq", "r2_bucket", "vidseek-videos") in client.table_stub.calls
    assert ("eq", "r2_object_key", "videos/job-42/clip.mp4") in client.table_stub.calls


def test_an_object_nothing_describes_is_absence_rather_than_an_error() -> None:
    records, _ = _records([])

    assert records.get_by_object_key("vidseek-videos", "videos/nobody/clip.mp4") is None


def test_the_videos_from_one_page_come_back_newest_first() -> None:
    records, client = _records([ROW, ROW])
    found = records.find_by_source_url(RECORD.source_url)

    assert len(found) == 2
    assert ("order", "created_at", True) in client.table_stub.calls


def test_deleting_a_row_leaves_the_r2_object_alone() -> None:
    # Dropping a row is cheap and reversible; dropping the video is neither, so removing
    # the two together belongs to whoever decided the video should go away.
    records, client = _records([])
    records.delete(ROW["id"])

    assert ("delete",) in client.table_stub.calls
    assert ("eq", "id", ROW["id"]) in client.table_stub.calls


def test_a_column_this_backend_does_not_know_about_is_ignored() -> None:
    # A later migration should not break a backend that has not been updated for it.
    stored = StoredVideoRecord.from_row({**ROW, "embedding_model": "text-embedding-3-small"})

    assert stored.video == RECORD


def _set_supabase_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    values = {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
        "SUPABASE_ANON_KEY": None,
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_supabase_env(monkeypatch)

    assert load_supabase_settings() == SETTINGS


def test_the_service_role_key_wins_over_the_anon_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The backend is a server. The anon key is the one meant to ship in a browser, and
    # every table here has row level security on with no policy that would admit it.
    _set_supabase_env(monkeypatch, SUPABASE_ANON_KEY="anon-key")

    assert load_supabase_settings().api_key == "service-role-key"


def test_the_anon_key_is_used_and_flagged_when_it_is_all_there_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_supabase_env(monkeypatch, SUPABASE_SERVICE_ROLE_KEY=None, SUPABASE_ANON_KEY="anon-key")
    settings = load_supabase_settings()

    assert settings.api_key == "anon-key"
    assert settings.uses_service_role is False


def test_a_missing_key_names_both_variables_it_would_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_supabase_env(monkeypatch, SUPABASE_SERVICE_ROLE_KEY=None)

    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY.*SUPABASE_ANON_KEY"):
        load_supabase_settings()


def test_a_missing_url_names_the_variable_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_supabase_env(monkeypatch, SUPABASE_URL=None)

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        load_supabase_settings()


def test_a_url_with_the_rest_path_already_on_it_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The client appends /rest/v1 itself, so this would request /rest/v1/rest/v1/videos
    # and come back as a routing error rather than as the misconfiguration it is.
    _set_supabase_env(monkeypatch, SUPABASE_URL="https://project.supabase.co/rest/v1")

    with pytest.raises(RuntimeError, match="project URL alone"):
        load_supabase_settings()


def test_a_trailing_slash_on_the_url_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_supabase_env(monkeypatch, SUPABASE_URL="https://project.supabase.co/")

    assert load_supabase_settings().url == "https://project.supabase.co"


def test_a_url_that_is_not_a_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_supabase_env(monkeypatch, SUPABASE_URL="project.supabase.co")

    with pytest.raises(RuntimeError, match="project URL"):
        load_supabase_settings()


def test_half_a_configuration_counts_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # A checkout with a URL but no key should skip the database, not fail every job on
    # the last step. The missing half is then named by load_supabase_settings.
    _set_supabase_env(monkeypatch, SUPABASE_SERVICE_ROLE_KEY=None)

    assert is_supabase_configured() is False


def test_a_configured_project_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_supabase_env(monkeypatch)

    assert is_supabase_configured() is True
