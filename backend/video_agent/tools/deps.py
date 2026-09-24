"""Dependencies injected into every conversation tool's RunContext."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..citations import AnswerDraft


@dataclass
class ConversationDeps:
    """Per-run state the application supplies when a conversation/agent run starts."""

    video_id: str
    timestamps_reliable: bool = True

    # Where the viewer's player was when the question was sent, in seconds; None when the
    # page gave no position. What a deictic question ("what is this?") points at.
    current_time_seconds: float | None = None

    # Shared, and deliberately mutable: the runner fills it as the agent retrieves and
    # writes, the citation check reads it to decide what the answer may claim, and the API
    # falls back to it when a run ends with no checked answer to send. All three need the
    # same per-run record, and deps is the one thing all three already hold.
    draft: AnswerDraft = field(default_factory=AnswerDraft)

    # The connection pool every tool's store is built on, rather than a store per tool: a
    # store holds nothing but its pool, so injecting one per table would be injecting the
    # same thing several times over and would grow this class with every tool added. Left
    # as None outside a test, which is each store's own way of saying "the shared pool".
    pool: object | None = None
