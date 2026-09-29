"""How much one answer may spend on the video's picture: visual tool calls, and looks.

A visual question is paid per look, so each turn is capped: at most `MAX_VISUAL_TOOL_CALLS`
calls to the visual tools, and `MAX_LOOKS` of them looks. A look is one contact sheet, one
sequence or one close view, however many frames it holds. The transcript tools spend nothing.

The cap is soft. A visual tool asked for after the budget is spent does no work and says so,
and the tool that spends the last call says it was the last, so the agent answers with what it
has -- "not found" included -- instead of the run being cut off with nothing.

The counters are shared by tools the model calls in parallel, so they are changed under a lock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

MAX_VISUAL_TOOL_CALLS = 6
MAX_LOOKS = 4

VISUAL_BUDGET_SPENT = (
    "This answer's visual budget is spent: no more visual tool calls will be answered. "
    "Answer now with what you have found, saying what you could not confirm."
)


@dataclass
class VisualBudget:
    """What one answer has spent on visual tools so far, and how much it had to spend."""

    max_tool_calls: int = MAX_VISUAL_TOOL_CALLS
    max_looks: int = MAX_LOOKS
    tool_calls_used: int = 0
    looks_used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def start_tool_call(self) -> bool:
        """Spend one visual tool call; False, spending nothing, when none is left."""
        with self._lock:
            if self.tool_calls_used >= self.max_tool_calls:
                return False
            self.tool_calls_used += 1
            return True

    def take_look(self) -> bool:
        """Spend one look; False, spending nothing, when none is left."""
        with self._lock:
            if self.looks_used >= self.max_looks:
                return False
            self.looks_used += 1
            return True

    def return_look(self) -> None:
        """Give back a look that was granted but never shown, because extracting its frames failed."""
        with self._lock:
            self.looks_used = max(0, self.looks_used - 1)

    def remaining(self) -> str:
        """What is left, in the words a tool result tells the agent."""
        with self._lock:
            calls = self.max_tool_calls - self.tool_calls_used
            looks = self.max_looks - self.looks_used
        if calls <= 0:
            return (
                f"That was your last visual tool call ({_looks(looks)} unused). "
                "Answer now with what you have."
            )
        return f"{calls} visual tool call{'s' if calls != 1 else ''} and {_looks(looks)} left."


def _looks(count: int) -> str:
    return f"{count} look{'s' if count != 1 else ''}"
