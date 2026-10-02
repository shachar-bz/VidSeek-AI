"""Wakes a user's open library progress streams when one of their jobs changes.

The job manager writes progress from its worker threads, while each progress stream is a
coroutine waiting on the API's event loop. This is the bridge between the two: a write
calls `notify(user_id)`, and every stream that user has open is woken to re-read the
database. It carries no job data on purpose -- Postgres stays the one source of truth for
what a library row looks like, so the stage logic is never duplicated here.

In memory, so it reaches only streams served by this process. That matches the job
manager, which is single-process too; a multi-worker deployment would back the same two
methods with Postgres `LISTEN`/`NOTIFY` instead.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_Waiter = tuple[asyncio.AbstractEventLoop, asyncio.Event]


class LibraryChangeNotifier:
    """Per-user wake-up signals, safe to fire from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[str, set[_Waiter]] = {}

    @contextmanager
    def subscribe(self, user_id: str) -> Iterator[asyncio.Event]:
        """An event set whenever this user's library changes, for as long as the block runs.

        Must be entered on the event loop that will wait on the event, because `notify`
        sets it through that loop.
        """
        waiter = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._waiters.setdefault(user_id, set()).add(waiter)
        try:
            yield waiter[1]
        finally:
            with self._lock:
                waiters = self._waiters.get(user_id)
                if waiters is not None:
                    waiters.discard(waiter)
                    if not waiters:
                        del self._waiters[user_id]

    def notify(self, user_id: str) -> None:
        """Wake every stream this user has open; a no-op when none is."""
        with self._lock:
            waiters = list(self._waiters.get(user_id, ()))
        for loop, wake in waiters:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                # The loop closed under a stream that had not unsubscribed yet, which only
                # happens at shutdown; there is nobody left to wake.
                pass
