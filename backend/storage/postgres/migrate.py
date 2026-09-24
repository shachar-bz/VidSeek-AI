"""Applies the SQL migrations in `migrations/` to the configured database, in order, once.

The schema used to be applied by hand, because the HTTP row API it was reached through
acts on rows and has no CREATE TABLE: there was nowhere for a migration to run from. A real
connection removes that constraint, so the schema is now applied by this runner instead of
by whoever remembers to paste it into a SQL editor.

Each file runs inside its own transaction and is recorded in `schema_migrations` when it
succeeds, so a failure half way through leaves the files before it applied and the file
that failed not applied at all. Re-running only applies what is missing, which makes this
safe to run on every deploy and safe to run twice by accident.

Run it with:

    python -m backend.storage.postgres.migrate
    python -m backend.storage.postgres.migrate --dry-run

Needs AZURE_DATABASE_URL in `backend/.env`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

from .connection import build_pool, shared_pool
from .settings import URL_NAME

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATIONS_GLOB = "*.sql"

# Every applied filename is recorded here, which is what makes "apply what is missing"
# answerable. Created by the runner rather than by a migration, since it has to exist
# before the first one can be recorded.
MIGRATIONS_TABLE = "schema_migrations"

CREATE_MIGRATIONS_TABLE = f"""
create table if not exists public.{MIGRATIONS_TABLE} (
    filename text primary key,
    applied_at timestamptz not null default now()
)
"""

# The migrations that create an extension are the only ones that can fail for a reason
# outside the schema, and the message Postgres gives for it does not mention the setting that
# fixes it. Each is mapped to the name the extension has in the `azure.extensions` list.
EXTENSIONS_MIGRATION = "0001_extensions.sql"
TRIGRAM_EXTENSION_MIGRATION = "0023_trigram_extension.sql"
EXTENSION_MIGRATIONS = {EXTENSIONS_MIGRATION: "VECTOR", TRIGRAM_EXTENSION_MIGRATION: "PG_TRGM"}
AZURE_EXTENSION_HELP = (
    "Applying {filename} failed. On Azure Database for PostgreSQL Flexible Server an "
    "extension must be allow-listed before any role may create it: open the server in the "
    "Azure portal, go to Settings > Server parameters, search for `azure.extensions`, tick "
    "{extension}, and save. The server applies the change without a restart. Then run this "
    "again. The underlying error follows.\n\n{error}"
)

logger = logging.getLogger(__name__)


def migration_files() -> list[Path]:
    """Every migration on disk, in the order they must be applied.

    Sorted by filename, which is why they are numbered. Nothing here knows what a migration
    contains, so a file whose number puts it before the table it depends on is a mistake
    that only shows up when it runs.
    """
    return sorted(MIGRATIONS_DIR.glob(MIGRATIONS_GLOB))


def applied_filenames(pool=None) -> set[str]:
    """The migrations this database has already had applied."""
    with (pool or shared_pool()).connection() as connection:
        connection.execute(CREATE_MIGRATIONS_TABLE)
        rows = connection.execute(
            f"select filename from public.{MIGRATIONS_TABLE}"
        ).fetchall()
    return {row["filename"] for row in rows}


def pending_migrations(pool=None) -> list[Path]:
    """The migrations on disk that this database has not had applied yet."""
    applied = applied_filenames(pool)
    return [path for path in migration_files() if path.name not in applied]


def apply_migrations(pool=None, *, dry_run: bool = False) -> list[str]:
    """Apply every pending migration in order, and return the names of those applied.

    A dry run reports what would be applied and changes nothing, which is the check worth
    making against a database that already holds something.
    """
    resolved_pool = pool or shared_pool()
    pending = pending_migrations(resolved_pool)
    if not pending:
        logger.info("Database is up to date; %d migrations already applied", len(migration_files()))
        return []
    if dry_run:
        for path in pending:
            logger.info("Would apply %s", path.name)
        return [path.name for path in pending]

    applied: list[str] = []
    for path in pending:
        _apply_one(resolved_pool, path)
        applied.append(path.name)
    return applied


def _apply_one(pool, path: Path) -> None:
    """Run one migration and record it, both inside the same transaction.

    Recording the file in the same transaction that runs it is what keeps the two from
    disagreeing: a migration that half applied and was then marked done would be invisible
    to every later run.
    """
    statements = path.read_text(encoding="utf-8")
    try:
        with pool.connection() as connection:
            connection.execute(statements)
            connection.execute(
                f"insert into public.{MIGRATIONS_TABLE} (filename) values (%s)",
                (path.name,),
            )
    except psycopg.Error as error:
        extension = EXTENSION_MIGRATIONS.get(path.name)
        if extension is not None:
            raise RuntimeError(
                AZURE_EXTENSION_HELP.format(
                    filename=path.name, extension=extension, error=error
                )
            ) from error
        raise
    logger.info("Applied %s", path.name)


def main(argv: list[str] | None = None) -> int:
    """Apply the migrations from the command line, reporting what happened."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the migrations that would be applied, and change nothing",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        pool = build_pool()
    except Exception as error:
        # A database that cannot be reached at all is the common first run, so it is worth
        # saying which variable points at it rather than only what the driver said.
        print(f"Could not connect to the database ({URL_NAME}): {error}", file=sys.stderr)
        return 1

    try:
        applied = apply_migrations(pool, dry_run=arguments.dry_run)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        pool.close()

    if not applied:
        print("Nothing to apply.")
    elif arguments.dry_run:
        print(f"{len(applied)} migration(s) would be applied.")
    else:
        print(f"Applied {len(applied)} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
