"""A Pydantic AI tool that answers a question about what the video shows, through the visual sub-agent.

The main agent's only visual tool, and its only way to learn what is on screen: it never sees
a frame and has no visual search of its own. The sub-agent (`backend/visual_agent/`) does the
looking and hands back text, with findings whose `start_seconds`/`end_seconds` the citation
check collects like any other retrieved moment. The viewer's position comes from the deps,
never from the model, so "what is this?" points at the frame the viewer actually had on screen.
"""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from backend.visual_agent import VisualInvestigation, run_investigation

from ..deps import ConversationDeps

FAILED_ANSWER = "The visual investigation failed, so nothing about what the video shows could be checked."

logger = logging.getLogger(__name__)


async def investigate_visual(
    ctx: RunContext[ConversationDeps],
    question: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> VisualInvestigation:
    """Answer a question about what the video shows: the picture, on-screen text, actions.

    Call this only for a visual question the user asked -- what is on screen, what a slide,
    board or diagram says or means, where something is, what someone does -- or a question
    pointing at the screen ("what is this?", "here"). Never for what was said. The viewer's
    current position in the video is passed along automatically.

    Args:
        question: The user's visual question, in full, in their words.
        start_seconds: The start of the part of the video the question is about, in seconds.
            Give it only when sure which part is meant (the user named a chapter or a time);
            leave it out otherwise.
        end_seconds: The end of that part, in seconds. Same rule as start_seconds.

    Returns:
        The answer, and the moments it rests on, each with its times, chapter and whether it
        was seen in a frame, read on screen, or heard.
    """
    try:
        return await run_investigation(
            question,
            video_id=ctx.deps.video_id,
            current_time_seconds=ctx.deps.current_time_seconds,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            pool=ctx.deps.pool,
        )
    except Exception:
        # A failed look (the model provider down, a missing key) should cost the user this
        # tool's answer, not the whole reply.
        logger.exception("A visual investigation of video %s failed", ctx.deps.video_id)
        return VisualInvestigation(answer=FAILED_ANSWER, findings=[])
