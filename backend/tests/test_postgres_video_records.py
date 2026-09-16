"""Tests for the PostgreSQL settings and the `videos` table the backend writes through."""

import pytest

from backend.storage.postgres import (
    PostgresSettings,
    PostgresVideoRecords,
    StoredVideoRecord,
    VideoRecord,
    is_postgres_configured,
)
from backend.storage.postgres.settings import load_postgres_settings
from backend.storage.postgres.video_records import TABLE_NAME
from backend.tests.fake_postgres import FakePool

URL = (
    "postgresql://vidseek:secret@vidseek.postgres.database.azure.com:5432/"
    "vidseek?sslmode=require"
)
SETTINGS = PostgresSettings(url=URL)

RECORD = VideoRecord(
    source="youtube_pipeline",
    source_url="https://www.youtube.com/watch?v=abc",
    title="A Talk",
    blob_container="videos",
    blob_name="videos/job-42/clip.mp4",
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


def _records(rows: list[dict] | None = None) -> tuple[PostgresVideoRecords, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresVideoRecords(pool=pool), pool


def test_a_video_carries_the_account_that_requested_it() -> None:
    records, pool = _records([{**ROW, "user_id": "11111111-2222-3333-4444-555555555555"}])
    stored = records.upsert(VideoRecord(**{**RECORD.to_row(), "user_id": "11111111-2222-3333-4444-555555555555"}))

    assert stored.video.user_id == "11111111-2222-3333-4444-555555555555"
    assert '"user_id"' in pool.statements[0]


def test_a_video_with_no_signed_in_requester_carries_no_owner() -> None:
    records, pool = _records([ROW])
    stored = records.upsert(RECORD)

    assert stored.video.user_id is None


def test_a_video_is_upserted_against_the_blob_it_describes() -> None:
    records, pool = _records([ROW])
    stored = records.upsert(RECORD)

    statement = pool.statements[0]
    assert f'insert into public."{TABLE_NAME}"' in statement
    assert 'on conflict ("blob_container", "blob_name") do update set' in statement
    assert stored.id == ROW["id"]
    assert stored.video == RECORD


def test_every_column_the_record_carries_is_written_in_one_fixed_order() -> None:
    # The statement's columns and its bound values are built from the same dataclass, so a
    # field added to VideoRecord cannot end up in one and not the other.
    records, pool = _records([ROW])
    records.upsert(RECORD)

    row = RECORD.to_row()
    assert pool.recorded[0].parameters == [row[name] for name in row]


def test_an_unset_field_is_written_as_null_rather_than_left_out() -> None:
    # The write is an upsert, so an omitted column keeps whatever an earlier run put
    # there: a video re-downloaded without a transcript would still claim the old source.
    records, pool = _records([ROW])
    records.upsert(VideoRecord(**{**RECORD.to_row(), "transcript_source": None}))

    assert None in pool.recorded[0].parameters


def test_the_columns_that_matched_are_not_reassigned_to_themselves() -> None:
    # `do update set blob_name = excluded.blob_name` is what matched the row in the first
    # place, so setting it says nothing.
    records, pool = _records([ROW])
    records.upsert(RECORD)

    assert '"blob_name" = excluded."blob_name"' not in pool.statements[0]
    assert '"source_url" = excluded."source_url"' in pool.statements[0]


def test_an_upsert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    # The statement ends in `returning *`, so an empty answer means the write did not land.
    records, _ = _records([])

    with pytest.raises(RuntimeError, match="returned no row"):
        records.upsert(RECORD)


def test_a_video_is_looked_up_by_container_as_well_as_name() -> None:
    # A blob name alone does not identify a file; the same name in another container is
    # another video, and this project has already changed its storage layout once.
    records, pool = _records([ROW])
    found = records.get_by_blob_name("videos", "videos/job-42/clip.mp4")

    assert found is not None and found.video == RECORD
    assert "blob_container = %s and blob_name = %s" in pool.statements[0]
    assert pool.recorded[0].parameters == ("videos", "videos/job-42/clip.mp4")


def test_a_blob_nothing_describes_is_absence_rather_than_an_error() -> None:
    records, _ = _records([])

    assert records.get_by_blob_name("videos", "videos/nobody/clip.mp4") is None


def test_the_videos_from_one_page_come_back_newest_first() -> None:
    records, pool = _records([ROW, ROW])
    found = records.find_by_source_url(RECORD.source_url)

    assert len(found) == 2
    assert "order by created_at desc" in pool.statements[0]


def test_deleting_a_row_leaves_the_stored_blob_alone() -> None:
    # Dropping a row is cheap and reversible; dropping the video is neither, so removing
    # the two together belongs to whoever decided the video should go away.
    records, pool = _records([])
    records.delete(ROW["id"])

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (ROW["id"],)


def test_the_row_id_is_bound_as_a_uuid_rather_than_as_text() -> None:
    # `videos.id` is a uuid column and the store passes a Python string, which Postgres
    # will not coerce on its own: without the cast the delete fails as a type error.
    records, pool = _records([])
    records.delete(ROW["id"])

    assert "%s::uuid" in pool.statements[0]


def test_a_column_this_backend_does_not_know_about_is_ignored() -> None:
    # A later migration should not break a backend that has not been updated for it.
    stored = StoredVideoRecord.from_row({**ROW, "embedding_model": "text-embedding-3-small"})

    assert stored.video == RECORD


def test_a_timestamp_comes_back_as_text_whatever_the_driver_decoded_it_into() -> None:
    # The driver hands back a datetime; the dataclass carries the ISO string the rest of
    # the pipeline passes around.
    from datetime import datetime, timezone

    moment = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    stored = StoredVideoRecord.from_row({**ROW, "created_at": moment, "updated_at": moment})

    assert stored.created_at == "2026-09-14T10:00:00+00:00"


def _set_postgres_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    values = {"AZURE_DATABASE_URL": URL, "ASURE_DATABASE_URL": None, **overrides}
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch)

    assert load_postgres_settings() == SETTINGS


def test_the_misspelled_variable_is_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # ASURE_DATABASE_URL is what this project's own .env was first written with. A
    # checkout carrying it should connect rather than report a variable it has set.
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL=None, ASURE_DATABASE_URL=URL)

    assert load_postgres_settings().url == URL


def test_the_correct_spelling_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch, ASURE_DATABASE_URL="postgresql://old@host:5432/db")

    assert load_postgres_settings().url == URL


def test_a_missing_url_names_the_variable_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL=None)

    with pytest.raises(RuntimeError, match="AZURE_DATABASE_URL"):
        load_postgres_settings()


def test_a_url_that_is_not_a_connection_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL="https://vidseek.database.azure.com")

    with pytest.raises(RuntimeError, match="postgresql://"):
        load_postgres_settings()


def test_the_older_postgres_scheme_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    # `postgres://` is the same thing spelled the older way, and libpq still takes it.
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL="postgres://user@host:5432/db")

    assert load_postgres_settings().url == "postgres://user@host:5432/db"


def test_a_url_with_no_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL="postgresql:///vidseek")

    with pytest.raises(RuntimeError, match="names no host"):
        load_postgres_settings()


def test_a_url_without_tls_is_warned_about_rather_than_refused(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Azure refuses the connection itself, and a local Postgres used for a test has no
    # reason to be turned away here, so this is the server's decision and not this code's.
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL="postgresql://user@localhost:5432/db")

    with caplog.at_level("WARNING"):
        settings = load_postgres_settings()

    assert settings.url == "postgresql://user@localhost:5432/db"
    assert "sslmode=require" in caplog.text


def test_the_host_is_readable_without_the_password_beside_it() -> None:
    # Anything that logs which server it reached must not log the credential to reach it.
    assert SETTINGS.host == "vidseek.postgres.database.azure.com"
    assert "secret" not in SETTINGS.host


def test_an_unconfigured_checkout_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    # A checkout with no database should skip recording, not fail every job on its last
    # step; the video is already durable in Blob Storage by then.
    _set_postgres_env(monkeypatch, AZURE_DATABASE_URL=None)

    assert is_postgres_configured() is False


def test_a_configured_database_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_postgres_env(monkeypatch)

    assert is_postgres_configured() is True
