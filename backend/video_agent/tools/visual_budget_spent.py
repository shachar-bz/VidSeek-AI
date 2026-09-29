"""What any visual tool answers once the turn's visual budget is spent: no work done, and why."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..visual_budget import VISUAL_BUDGET_SPENT


class VisualBudgetSpent(BaseModel):
    """The tool did nothing, because this answer has no visual tool calls left."""

    budget_spent: bool = True
    message: str = Field(default=VISUAL_BUDGET_SPENT, description="What to do instead.")
