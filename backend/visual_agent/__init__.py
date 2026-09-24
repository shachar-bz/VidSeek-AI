"""Visual sub-agent package: investigates what a video shows and answers the main agent in text."""

from .budget import MAX_IMAGES, MAX_TOOL_CALLS, InvestigationBudget
from .result import VisualFinding, VisualInvestigation
from .runner import MODEL_NAME, build_visual_agent, run_investigation
from .tools.deps import VisualDeps

__all__ = [
    "MAX_IMAGES",
    "MAX_TOOL_CALLS",
    "MODEL_NAME",
    "InvestigationBudget",
    "VisualDeps",
    "VisualFinding",
    "VisualInvestigation",
    "build_visual_agent",
    "run_investigation",
]
