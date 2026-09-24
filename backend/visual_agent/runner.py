"""Runs one visual investigation: a question about what the video shows in, a text answer out.

The sub-agent is stateless per call. It is built with its tools, given the question, the
viewer's position and the optional time range, and run to a `VisualInvestigation`; follow-up
context lives in the main agent's history, not here.

Two models take part. The planner (`MODEL_NAME`) chooses which tools to call and writes the
answer; it never receives an image. `view_frames` and `view_sequence` send frames to the image
model (`image_analysis.py`) and hand the planner its words.

The answer's findings are checked before they leave (`result.py`): a finding whose times no
tool returned is sent back once, and dropped if the second answer still carries it, so an
answer is never lost to a bad citation. A run stopped by the hard usage limit returns an
answer saying the investigation could not finish rather than failing the main agent's turn.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.core import config
from backend.services.video_frames import format_timestamp

from .budget import USAGE_LIMITS
from .prompt import VISUAL_AGENT_PROMPT
from .result import VisualInvestigation, unsupported_findings
from .tools.deps import VisualDeps
from .tools.get_transcript_window import get_transcript_window
from .tools.read_frame_text import read_frame_text
from .tools.search_visual_moments import search_visual_moments
from .tools.search_visual_text import search_visual_text
from .tools.view_frames import view_frames
from .tools.view_sequence import view_sequence

# The same key every other OpenAI call site in the backend reads (see `video_agent/runner.py`).
API_KEY_NAME = "OPENAI_API_KEY_DUDU"
MODEL_NAME = "gpt-6-sol"
TOOLS = (
    search_visual_moments,
    search_visual_text,
    view_frames,
    view_sequence,
    read_frame_text,
    get_transcript_window,
)

# Answers sent back by the findings check before unsupported findings are dropped instead.
FINDINGS_RETRIES = 1

OUT_OF_BUDGET_ANSWER = (
    "The visual investigation used its whole budget before it could reach an answer."
)

logger = logging.getLogger(__name__)


def build_visual_agent(model: str = MODEL_NAME) -> Agent[VisualDeps, VisualInvestigation]:
    """The sub-agent with its tools and the findings check."""
    agent = Agent(
        # The Responses API rather than Chat Completions: gpt-6-sol refuses function tools on
        # Chat Completions while it reasons.
        OpenAIResponsesModel(model, provider=OpenAIProvider(api_key=config.require(API_KEY_NAME))),
        deps_type=VisualDeps,
        output_type=VisualInvestigation,
        instructions=VISUAL_AGENT_PROMPT,
        tools=list(TOOLS),
        retries={"output": FINDINGS_RETRIES},
        defer_model_check=True,
    )
    agent.output_validator(verify_findings)
    return agent


def verify_findings(
    ctx: RunContext[VisualDeps], output: VisualInvestigation
) -> VisualInvestigation:
    """Send back an answer whose findings name moments no tool returned; drop them on the last try."""
    unsupported = unsupported_findings(output.findings, ctx.deps.spans)
    if not unsupported:
        return output
    if ctx.retry < ctx.max_retries:
        times = ", ".join(
            f"{format_timestamp(finding.start_seconds)}-{format_timestamp(finding.end_seconds)}"
            for finding in unsupported
        )
        raise ModelRetry(
            f"These findings name moments no tool returned during this investigation: {times}. "
            "Use only times that appeared in a tool result, or leave the finding out."
        )
    logger.warning("Dropped %d findings no tool supported", len(unsupported))
    return output.model_copy(
        update={"findings": [finding for finding in output.findings if finding not in unsupported]}
    )


async def run_investigation(
    question: str,
    *,
    video_id: str,
    current_time_seconds: float | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    pool: object | None = None,
    agent: Agent[VisualDeps, VisualInvestigation] | None = None,
    deps: VisualDeps | None = None,
) -> VisualInvestigation:
    """Investigate one question about what the video shows, and answer it in text."""
    agent = agent or build_visual_agent()
    deps = deps or VisualDeps(
        video_id=video_id, current_time_seconds=current_time_seconds, pool=pool
    )
    prompt = investigation_prompt(
        question,
        current_time_seconds=deps.current_time_seconds,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    try:
        result = await agent.run(prompt, deps=deps, usage_limits=USAGE_LIMITS)
    except UsageLimitExceeded:
        logger.warning("A visual investigation of video %s hit its hard usage limit", video_id)
        return VisualInvestigation(answer=OUT_OF_BUDGET_ANSWER, findings=[])
    return result.output


def investigation_prompt(
    question: str,
    *,
    current_time_seconds: float | None,
    start_seconds: float | None,
    end_seconds: float | None,
) -> str:
    """The question, where the viewer was, and the part of the video to look in, if one was given."""
    lines = [f"Question: {question}"]
    if current_time_seconds is None:
        lines.append("The viewer's position in the video is not known.")
    else:
        lines.append(
            f"The viewer's player was at {format_timestamp(current_time_seconds)} "
            f"({current_time_seconds:.1f} seconds) when the question was asked."
        )
    if start_seconds is not None or end_seconds is not None:
        start = _place(start_seconds, "the start")
        end = _place(end_seconds, "the end")
        lines.append(f"The question is about the part of the video from {start} to {end}.")
    else:
        lines.append("No part of the video was named; the question may be about any of it.")
    return "\n".join(lines)


def _place(seconds: float | None, open_end: str) -> str:
    """A time both ways the tools speak it, `MM:SS (123.4 s)`, or the open end when there is none."""
    if seconds is None:
        return open_end
    return f"{format_timestamp(seconds)} ({seconds:.1f} s)"
