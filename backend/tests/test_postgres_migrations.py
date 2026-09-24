"""Tests for the runner that applies the SQL migrations, and for the migrations on disk."""

from contextlib import contextmanager

import psycopg
import pytest

from backend.storage.postgres import migrate
from backend.storage.postgres.migrate import (
    EXTENSIONS_MIGRATION,
    MIGRATIONS_TABLE,
    apply_migrations,
    migration_files,
    pending_migrations,
)


class FakeMigrationConnection:
    """Answers the three kinds of statement the runner sends, and records the rest."""

    def __init__(self, pool):
        self._pool = pool

    def execute(self, statement, parameters=None):
        text = str(statement)
        if f"insert into public.{MIGRATIONS_TABLE}" in text:
            self._pool.applied.append(parameters[0])
            return _Rows([])
        if f"select filename from public.{MIGRATIONS_TABLE}" in text:
            return _Rows([{"filename": name} for name in self._pool.applied])
        if f"create table if not exists public.{MIGRATIONS_TABLE}" in text:
            return _Rows([])
        self._pool.ran.append(text)
        if self._pool.fails_on and self._pool.fails_on in text:
            raise psycopg.errors.FeatureNotSupported('extension "vector" is not allow-listed')
        return _Rows([])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeMigrationPool:
    """A database that remembers which migrations it has had applied.

    `fails_on` makes one migration raise the way a server that refuses a statement does,
    which is what the extension case needs: the file runs, is refused, and must not end up
    recorded as applied.
    """

    def __init__(self, applied: list[str] | None = None, fails_on: str | None = None):
        self.applied = list(applied or [])
        self.ran: list[str] = []
        self.fails_on = fails_on
        self.closed = False

    @contextmanager
    def connection(self):
        yield FakeMigrationConnection(self)

    def close(self) -> None:
        self.closed = True


def test_every_migration_on_disk_is_picked_up() -> None:
    # A file added later must not be silently skipped, which is what a hardcoded list in
    # the runner would eventually cause.
    names = [path.name for path in migration_files()]

    assert names == sorted(names)
    assert names[0] == EXTENSIONS_MIGRATION
    assert all(name.endswith(".sql") for name in names)


def test_no_two_migrations_share_a_number() -> None:
    # They are applied in filename order, so two files numbered alike would be applied in
    # whatever order the rest of the name happened to sort in.
    numbers = [path.name.split("_", 1)[0] for path in migration_files()]

    assert len(numbers) == len(set(numbers))


def test_a_table_is_never_created_before_the_extension_it_needs() -> None:
    # Ordering is the one thing the runner cannot check: it applies files in order without
    # knowing what is in them.
    names = [path.name for path in migration_files()]

    assert names.index("0002_videos.sql") < names.index("0003_transcript_segments.sql")
    assert names.index("0005_chapters.sql") < names.index("0006_memories.sql")
    assert names.index("0006_memories.sql") < names.index("0007_embeddings.sql")
    # The website's tables: sessions and video_jobs reference users, video_insights and the
    # deduplication column reference videos, and an ANN index cannot be built until 0010
    # and 0011 have fixed each embedding column's dimension.
    assert names.index("0008_users.sql") < names.index("0017_sessions.sql")
    assert names.index("0008_users.sql") < names.index("0018_video_jobs.sql")
    assert names.index("0002_videos.sql") < names.index("0018_video_jobs.sql")
    assert names.index("0002_videos.sql") < names.index("0019_videos_normalized_source_url.sql")
    assert names.index("0002_videos.sql") < names.index("0020_video_insights.sql")
    assert names.index("0010_memory_embeddings_video_chapter.sql") < names.index(
        "0021_embedding_ann_indexes.sql"
    )
    assert names.index("0011_chapter_embeddings_video_times.sql") < names.index(
        "0021_embedding_ann_indexes.sql"
    )
    # Keyframe text goes onto the keyframes 0022 creates, indexed with the extension 0023 does.
    assert names.index("0022_video_visual_index.sql") < names.index("0024_keyframe_on_screen_text.sql")
    assert names.index("0023_trigram_extension.sql") < names.index("0024_keyframe_on_screen_text.sql")
    # The trigram index and its extension are dropped only after they were created.
    assert names.index("0024_keyframe_on_screen_text.sql") < names.index(
        "0026_drop_keyframe_text_trigram_index.sql"
    )


def test_a_fresh_database_has_every_migration_pending() -> None:
    pool = FakeMigrationPool()

    assert pending_migrations(pool) == migration_files()


def test_migrations_are_applied_in_filename_order() -> None:
    pool = FakeMigrationPool()
    applied = apply_migrations(pool)

    assert applied == [path.name for path in migration_files()]
    assert pool.applied == applied


def test_only_what_is_missing_is_applied() -> None:
    already = [path.name for path in migration_files()[:3]]
    pool = FakeMigrationPool(applied=already)

    assert apply_migrations(pool) == [path.name for path in migration_files()[3:]]


def test_a_second_run_applies_nothing() -> None:
    pool = FakeMigrationPool()
    apply_migrations(pool)
    ran_once = len(pool.ran)

    assert apply_migrations(pool) == []
    assert len(pool.ran) == ran_once


def test_a_dry_run_reports_what_would_apply_and_changes_nothing() -> None:
    pool = FakeMigrationPool()
    would = apply_migrations(pool, dry_run=True)

    assert would == [path.name for path in migration_files()]
    assert pool.applied == []
    assert pool.ran == []


def test_a_refused_extension_names_the_azure_setting_that_fixes_it() -> None:
    # Postgres reports this as a plain statement failure, which does not mention the
    # server parameter that has to be changed before any role may create the extension.
    pool = FakeMigrationPool(fails_on="create extension if not exists vector")

    with pytest.raises(RuntimeError, match="azure.extensions"):
        apply_migrations(pool)


def test_a_refused_trigram_extension_names_its_own_setting() -> None:
    pool = FakeMigrationPool(fails_on="create extension if not exists pg_trgm")

    with pytest.raises(RuntimeError, match="tick PG_TRGM"):
        apply_migrations(pool)

    assert "0023_trigram_extension.sql" not in pool.applied
    assert "0022_video_visual_index.sql" in pool.applied


def test_a_migration_that_failed_is_not_recorded_as_applied() -> None:
    # Recording it would make the failure invisible to every later run, and the tables it
    # was supposed to create would never appear.
    pool = FakeMigrationPool(fails_on="create extension if not exists vector")

    with pytest.raises(RuntimeError):
        apply_migrations(pool)

    assert pool.applied == []


def test_a_failure_leaves_the_migrations_before_it_applied() -> None:
    pool = FakeMigrationPool(fails_on="create table if not exists public.comments")

    with pytest.raises(psycopg.Error):
        apply_migrations(pool)

    assert pool.applied == [path.name for path in migration_files()[:3]]


def test_the_command_line_reports_a_database_it_cannot_reach(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # The first run against a new server is the common case for this, and the driver's own
    # message does not say which variable pointed at it.
    def refuse():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(migrate, "build_pool", refuse)

    assert migrate.main([]) == 1
    assert "AZURE_DATABASE_URL" in capsys.readouterr().err


def test_the_command_line_closes_the_pool_even_when_a_migration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakeMigrationPool(fails_on="create extension if not exists vector")
    monkeypatch.setattr(migrate, "build_pool", lambda: pool)

    assert migrate.main([]) == 1
    assert pool.closed is True


def test_the_trigram_index_goes_before_the_extension_it_is_built_with() -> None:
    [path] = [path for path in migration_files() if path.name.startswith("0026_")]
    statements = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("--")
    ]

    assert statements == [
        "drop index if exists public.video_keyframes_ocr_text_trgm_idx;",
        "drop extension if exists pg_trgm;",
    ]
