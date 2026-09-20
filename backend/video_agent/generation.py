"""Coordinates one cancellable, exactly-once-finalized generation per conversation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class ActiveGeneration:
    """Mutable coordination state shared by a message stream and its stop endpoint."""

    stop_requested: asyncio.Event = field(default_factory=asyncio.Event)
    finalize_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    finalized: bool = False

class GenerationRegistry:
    """Tracks active runs so stop requests cannot target old or newer generations."""

    def __init__(self) -> None:
        self._active: dict[str, ActiveGeneration] = {}
        self._lock = asyncio.Lock()

    async def start(self, conversation_id: str) -> ActiveGeneration | None:
        """Register a run, or return None when this conversation already has one."""

        async with self._lock:
            if conversation_id in self._active:
                return None
            generation = ActiveGeneration()
            self._active[conversation_id] = generation
            return generation

    async def request_stop(self, conversation_id: str) -> bool:
        """Signal the current run, if any, without waiting for stream finalization."""

        async with self._lock:
            generation = self._active.get(conversation_id)
            if generation is None:
                return False
            generation.stop_requested.set()
            return True

    async def finish(self, conversation_id: str, generation: ActiveGeneration) -> None:
        """Remove only the generation supplied, never a newer run for the same thread."""

        async with self._lock:
            if self._active.get(conversation_id) is generation:
                self._active.pop(conversation_id, None)
