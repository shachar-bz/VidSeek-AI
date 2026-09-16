"""A connection pool that records the SQL it was given instead of reaching a database.

Shared by the three store test modules rather than copied into each, because what they
need from it is identical: the statements the store built, the parameters it bound, and
whatever rows it was told to answer with. What differs between them is only the rows, which
each test supplies.

Statements are recorded as plain strings. A store may build one as a `psycopg.sql.Composed`
-- `PostgresVideoRecords` does, so that the column list comes from its own dataclass -- and
rendering it here is what lets a test assert on the SQL either kind produced without caring
which it was.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from psycopg import sql


@dataclass(frozen=True)
class RecordedStatement:
    """One statement the store asked to run, and what it bound to it."""

    statement: str
    parameters: object

    # Set when the statement was run once per row rather than once. `executemany` is what a
    # store uses to write a whole transcript, and a test that cannot tell the two apart
    # cannot tell a batched write from a loop of single ones.
    many: bool = False


class FakeCursor:
    """Records statements, and answers every read with the rows it was given."""

    def __init__(self, rows: list[dict], recorded: list[RecordedStatement]):
        self._rows = rows
        self._recorded = recorded

    def execute(self, statement, parameters=None) -> FakeCursor:
        self._recorded.append(RecordedStatement(_as_text(statement), parameters))
        return self

    def executemany(self, statement, rows) -> None:
        self._recorded.append(RecordedStatement(_as_text(statement), list(rows), many=True))

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return list(self._rows)

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_) -> None:
        return None


class FakeConnection:
    """One connection, whose `execute` and `cursor` share the same recording."""

    def __init__(self, rows: list[dict], recorded: list[RecordedStatement]):
        self._rows = rows
        self._recorded = recorded

    def execute(self, statement, parameters=None) -> FakeCursor:
        return FakeCursor(self._rows, self._recorded).execute(statement, parameters)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows, self._recorded)


@dataclass
class FakePool:
    """Stands in for the connection pool a store is handed.

    `transactions` counts how many times a connection was taken out, which is how a test
    checks that a replace wrote its rows and trimmed the leftovers as one unit rather than
    as two.
    """

    rows: list[dict] = field(default_factory=list)
    recorded: list[RecordedStatement] = field(default_factory=list)
    transactions: int = 0

    @contextmanager
    def connection(self):
        self.transactions += 1
        yield FakeConnection(self.rows, self.recorded)

    @property
    def statements(self) -> list[str]:
        """Just the SQL, for a test that only cares which statements ran."""
        return [item.statement for item in self.recorded]


def _as_text(statement) -> str:
    """One statement as SQL text, whichever of psycopg's forms it arrived in."""
    return statement.as_string(None) if isinstance(statement, (sql.Composed, sql.SQL)) else str(statement)
