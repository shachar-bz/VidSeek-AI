"""Dependencies injected into every conversation tool's RunContext."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConversationDeps:
    """Per-run state the application supplies when a conversation/agent run starts."""

    video_id: str

    # The connection pool every tool's store is built on, rather than a store per tool: a
    # store holds nothing but its pool, so injecting one per table would be injecting the
    # same thing several times over and would grow this class with every tool added. Left
    # as None outside a test, which is each store's own way of saying "the shared pool".
    pool: object | None = None
