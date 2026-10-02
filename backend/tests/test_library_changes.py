"""Tests for the per-user wake-up signals behind the library progress stream."""

from __future__ import annotations

import asyncio
import threading

from backend.services.library_changes import LibraryChangeNotifier


def test_a_notify_from_a_worker_thread_wakes_that_users_stream() -> None:
    changes = LibraryChangeNotifier()

    async def scenario() -> bool:
        with changes.subscribe("user-1") as wake:
            threading.Thread(target=changes.notify, args=("user-1",)).start()
            await asyncio.wait_for(wake.wait(), timeout=1)
            return wake.is_set()

    assert asyncio.run(scenario())


def test_a_notify_for_another_user_does_not_wake_the_stream() -> None:
    changes = LibraryChangeNotifier()

    async def scenario() -> bool:
        with changes.subscribe("user-1") as wake:
            changes.notify("user-2")
            await asyncio.sleep(0.01)
            return wake.is_set()

    assert not asyncio.run(scenario())


def test_a_closed_stream_is_no_longer_woken() -> None:
    changes = LibraryChangeNotifier()

    async def scenario() -> bool:
        with changes.subscribe("user-1") as wake:
            pass
        changes.notify("user-1")
        await asyncio.sleep(0.01)
        return wake.is_set()

    assert not asyncio.run(scenario())
