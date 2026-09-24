"""How much one visual investigation may spend: tool calls, and images shown to the image model.

An investigation is paid per look, so it is capped: at most `MAX_TOOL_CALLS` tool calls and
`MAX_IMAGES` frames sent to the image model. The cap is soft first. A tool asked for after the
budget is spent does no work and says so, and the tool that spends the last call says it was the
last, so the agent answers with what it has -- "not found" and "low confidence" included --
instead of the run being cut off with nothing. `USAGE_LIMITS` is the hard stop behind that, a
little above the soft cap, for a model that keeps calling tools after being told to stop.

The counters are shared by tools the model calls in parallel, so they are changed under a lock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from pydantic_ai.usage import UsageLimits

MAX_TOOL_CALLS = 6
MAX_IMAGES = 8

# Calls past the soft cap that are still answered (with "budget spent") before the run is
# stopped outright, and model requests allowed: one per round of tool calls, one for the
# answer, and one more for an answer sent back by the findings check.
TOOL_CALLS_PAST_BUDGET = 2
USAGE_LIMITS = UsageLimits(
    tool_calls_limit=MAX_TOOL_CALLS + TOOL_CALLS_PAST_BUDGET,
    request_limit=MAX_TOOL_CALLS + 4,
)

BUDGET_SPENT = (
    "The investigation's budget is spent: no more tool calls will be answered. "
    "Answer now with what you have found, saying what you could not confirm."
)


@dataclass
class InvestigationBudget:
    """What one investigation has spent so far, and how much it had to spend."""

    max_tool_calls: int = MAX_TOOL_CALLS
    max_images: int = MAX_IMAGES
    tool_calls_used: int = 0
    images_used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def start_tool_call(self) -> bool:
        """Spend one tool call; False, spending nothing, when none is left."""
        with self._lock:
            if self.tool_calls_used >= self.max_tool_calls:
                return False
            self.tool_calls_used += 1
            return True

    def take_images(self, wanted: int) -> int:
        """Spend up to `wanted` images and say how many were granted; zero when none are left."""
        with self._lock:
            granted = max(0, min(wanted, self.max_images - self.images_used))
            self.images_used += granted
            return granted

    def return_images(self, count: int) -> None:
        """Give back images that were granted but never shown, because extracting them failed."""
        with self._lock:
            self.images_used = max(0, self.images_used - count)

    def remaining(self) -> str:
        """What is left, in the words a tool result tells the agent."""
        with self._lock:
            calls = self.max_tool_calls - self.tool_calls_used
            images = self.max_images - self.images_used
        if calls <= 0:
            return (
                f"That was your last tool call ({images} images unused). "
                "Answer now with what you have."
            )
        return f"{calls} tool calls and {images} images left."
