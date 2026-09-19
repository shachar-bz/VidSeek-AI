"""Tests for the `video_jobs` table: one companion job's live status, readable by anything."""

import pytest

from backend.storage.postgres import PostgresVideoJobs, StoredVideoJob, VideoJob
from backend.storage.postgres.video_jobs import TABLE_NAME
from backend.tests.fake_postgres import FakePool

USER_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"

JOB = VideoJob(
    id="deadbeefdeadbeefdeadbeefdeadbeef",
    page_url="https://example.com/watch",
    page_title="A Talk",
    status="running",
    phase="download",
    progress=0.25,
    message="Downloading...",
    user_id=USER_ID,
)

ROW = {
    "created_at": "2026-09-14T10:00:00+00:00",
    "updated_at": "2026-09-14T10:00:00+00:00",
    **JOB.to_row(),
}


def _jobs(rows: list[dict] | None = None) -> tuple[PostgresVideoJobs, FakePool]:
    pool = FakePool(rows=rows if rows is not None else [])
    return PostgresVideoJobs(pool=pool), pool


def test_a_job_is_upserted_against_its_own_id() -> None:
    jobs, pool = _jobs([ROW])
    stored = jobs.upsert(JOB)

    assert f'insert into public."{TABLE_NAME}"' in pool.statements[0]
    assert "on conflict (id) do update set" in pool.statements[0]
    assert stored.job == JOB


def test_only_the_progress_reporting_columns_are_reassigned_on_conflict() -> None:
    # page_url, page_title, user_id and acquisition_mode identify the job and who started
    # it; a later progress report must not be able to overwrite either.
    jobs, pool = _jobs([ROW])
    jobs.upsert(JOB)

    statement = pool.statements[0]
    assert '"status" = excluded."status"' in statement
    assert '"progress" = excluded."progress"' in statement
    assert '"video_id" = excluded."video_id"' in statement
    assert '"page_url" = excluded."page_url"' not in statement
    assert '"user_id" = excluded."user_id"' not in statement
    assert '"acquisition_mode" = excluded."acquisition_mode"' not in statement


def test_an_upsert_that_returns_no_row_is_an_error_rather_than_a_silent_success() -> None:
    jobs, _ = _jobs([])

    with pytest.raises(RuntimeError, match="returned no row"):
        jobs.upsert(JOB)


def test_a_job_is_read_back_only_for_the_user_who_started_it() -> None:
    jobs, pool = _jobs([ROW])
    found = jobs.get(JOB.id, USER_ID)

    assert found is not None and found.job == JOB
    assert "user_id = %s::uuid" in pool.statements[0]
    assert pool.recorded[0].parameters == (JOB.id, USER_ID)


def test_a_job_belonging_to_someone_else_is_absence_rather_than_an_error() -> None:
    jobs, _ = _jobs([])

    assert jobs.get(JOB.id, USER_ID) is None


def test_a_job_is_read_back_by_id_alone_for_the_companions_own_poll() -> None:
    jobs, pool = _jobs([ROW])
    found = jobs.get_by_id(JOB.id)

    assert found is not None and found.job == JOB
    assert "user_id" not in pool.statements[0]
    assert pool.recorded[0].parameters == (JOB.id,)


def test_get_by_id_of_a_job_nobody_recorded_is_absence_rather_than_an_error() -> None:
    jobs, _ = _jobs([])

    assert jobs.get_by_id(JOB.id) is None


def test_a_users_jobs_come_back_newest_first() -> None:
    jobs, pool = _jobs([ROW, ROW])
    found = jobs.list_for_user(USER_ID)

    assert len(found) == 2
    assert "order by created_at desc" in pool.statements[0]


def test_deleting_a_job_removes_only_that_row() -> None:
    jobs, pool = _jobs([])
    jobs.delete(JOB.id)

    assert pool.statements[0].startswith(f"delete from public.{TABLE_NAME}")
    assert pool.recorded[0].parameters == (JOB.id,)


def test_the_job_id_is_bound_as_plain_text_rather_than_a_uuid() -> None:
    # The companion generates ids as uuid4().hex, which is not a uuid literal.
    jobs, pool = _jobs([])
    jobs.delete(JOB.id)

    assert "::uuid" not in pool.statements[0]


def test_a_column_this_backend_does_not_know_about_is_ignored() -> None:
    stored = StoredVideoJob.from_row({**ROW, "worker_host": "companion-1"})

    assert stored.job == JOB
