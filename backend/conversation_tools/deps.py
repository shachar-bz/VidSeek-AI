"""Dependencies injected into every conversation tool's RunContext."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConversationDeps:
    """Per-run state the application supplies when a conversation/agent run starts."""

    video_id: str
