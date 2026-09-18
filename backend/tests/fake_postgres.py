"""A connection pool that records the SQL it was given instead of reaching a database.

Shared by the store test modules rather than copied into each, because what they need from
it is identical: the statements the store built, the parameters it bound, and whatever rows
it was told to answer with. What differs between them is only the rows, which each test
supplies.

A test gives those rows one of two ways. `rows` answers every read with the same list,
which is all a store that runs one query per call ever needs. `responses` answers the reads
in order, one list each, for a caller that runs several different queries in a single call
and would otherwise have to pretend they all return the same columns.

Statements are recorded as plain strings. A store may build one as a `psycopg.sql.Composed`
-- `PostgresVideoRecords` does, so that the column list comes from its own dataclass -- and
rendering it here is what lets a test assert on the SQL either kind produced without caring
which it was.
"""

from __future__ import annotations

from collections.abc import Callable
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
    """Records statements, and answers a read with the rows it is handed when it is read.

    The rows arrive through a callable rather than as a list, so that a pool answering reads
    in order hands over the next batch only once something actually fetches. A statement
    that writes and never fetches -- the trim half of a `replace` -- must not consume one.
    """

    def __init__(self, next_rows: Callable[[], list[dict]], recorded: list[RecordedStatement]):
        self._next_rows = next_rows
        self._fetched: list[dict] | None = None
        self._recorded = recorded

    def execute(self, statement, parameters=None) -> FakeCursor:
        self._recorded.append(RecordedStatement(_as_text(statement), parameters))
        return self

    def executemany(self, statement, rows) -> None:
        self._recorded.append(RecordedStatement(_as_text(statement), list(rows), many=True))

    def fetchone(self) -> dict | None:
        rows = self._rows()
        return rows[0] if rows else None

    def fetchall(self) -> list[dict]:
        return list(self._rows())

    def _rows(self) -> list[dict]:
        """This cursor's rows, taken once so two fetches on it see the same answer."""
        if self._fetched is None:
            self._fetched = self._next_rows()
        return self._fetched

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_) -> None:
        return None


class FakeConnection:
    """One connection, whose `execute` and `cursor` share the same recording."""

    def __init__(self, next_rows: Callable[[], list[dict]], recorded: list[RecordedStatement]):
        self._next_rows = next_rows
        self._recorded = recorded

    def execute(self, statement, parameters=None) -> FakeCursor:
        return FakeCursor(self._next_rows, self._recorded).execute(statement, parameters)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._next_rows, self._recorded)


@dataclass
class FakePool:
    """Stands in for the connection pool a store is handed.

    `transactions` counts how many times a connection was taken out, which is how a test
    checks that a replace wrote its rows and trimmed the leftovers as one unit rather than
    as two.
    """

    rows: list[dict] = field(default_factory=list)

    # One list of rows per read, in the order the reads happen, for a caller that runs
    # several different queries in one call. None means every read answers with `rows`.
    # Reads beyond the end of the list answer with nothing, the same as a query that matched
    # no row, so a test only has to supply the responses it cares about.
    responses: list[list[dict]] | None = None

    recorded: list[RecordedStatement] = field(default_factory=list)
    transactions: int = 0

    def __post_init__(self) -> None:
        self._pending = list(self.responses) if self.responses is not None else None

    @contextmanager
    def connection(self):
        self.transactions += 1
        yield FakeConnection(self._next_rows, self.recorded)

    def _next_rows(self) -> list[dict]:
        """The rows the read happening now is answered with."""
        if self._pending is None:
            return self.rows
        return self._pending.pop(0) if self._pending else []

    @property
    def statements(self) -> list[str]:
        """Just the SQL, for a test that only cares which statements ran."""
        return [item.statement for item in self.recorded]


def _as_text(statement) -> str:
    """One statement as SQL text, whichever of psycopg's forms it arrived in."""
    return statement.as_string(None) if isinstance(statement, (sql.Composed, sql.SQL)) else str(statement)
