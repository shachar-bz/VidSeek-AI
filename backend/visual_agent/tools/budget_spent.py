"""What any tool answers once the investigation's budget is spent: no work done, and why."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..budget import BUDGET_SPENT


class BudgetSpent(BaseModel):
    """The tool did nothing, because the investigation has no tool calls left."""

    budget_spent: bool = True
    message: str = Field(default=BUDGET_SPENT, description="What to do instead.")
