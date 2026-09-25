"""Model-backed agent runner and its provider-independent streaming events."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import TypeAdapter
from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRetry,
    PartDeltaEvent,
    PartStartEvent,
    RunContext,
    TextPartDelta,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.core import config
from backend.storage.postgres import StoredMessage

from . import citations
from .prompt import SYSTEM_PROMPT, VIEWER_COMMENTS_PROMPT
from .tools.deps import ConversationDeps
from .tools.get_chapter_context import get_chapter_context
from .tools.get_memory_context import get_memory_context
from .tools.get_video_info import get_video_info
from .tools.get_video_outline import get_video_outline
from .tools.get_viewer_comments import viewer_comments_tool
from .tools.investigate_visual import investigate_visual
from .tools.memories_semantic_search import memories_semantic_search

# Every other OpenAI call site in the backend (video_insights, grouper, segmenter,
# transcriber) reads this same key explicitly; pydantic_ai's default OpenAI provider
# looks for the standard OPENAI_API_KEY instead, which this project never sets.
API_KEY_NAME = "OPENAI_API_KEY_DUDU"
MODEL_NAME = "gpt-6-sol"
PARTIAL_TIMING_PROMPT = (
    "The current video's transcript timing may be unreliable. Warn the user when making "
    "timestamp-based statements, while still answering from the retrieved video content."
)
TOOLS = (
    get_video_info,
    get_video_outline,
    memories_semantic_search,
    get_chapter_context,
    get_memory_context,
    investigate_visual,
    # Offered only for a video with stored YouTube comments; see its `prepare`.
    viewer_comments_tool,
)


@dataclass(frozen=True)
class TextFragment:
    """A newly generated answer fragment."""

    text: str


@dataclass(frozen=True)
class ToolStarted:
    """A validated function-tool invocation about to run."""

    call_id: str
    tool: str
    arguments: dict
    started_at: str


@dataclass(frozen=True)
class ToolFinished:
    """A function-tool invocation that returned or failed validation/execution."""

    call_id: str
    summary: str | None
    finished_at: str
    error: str | None = None


AgentEvent = TextFragment | ToolStarted | ToolFinished


class ConversationAgentRunner(Protocol):
    """The injectable model boundary consumed by the conversation API."""

    async def stream(
        self,
        prompt: str,
        *,
        history: Sequence[StoredMessage],
        deps: ConversationDeps,
    ) -> AsyncIterator[AgentEvent]: ...


def build_agent(model: str = MODEL_NAME) -> Agent[ConversationDeps, str]:
    """Build the production agent: five transcript tools, one visual tool, and the comments
    tool a YouTube video with stored comments is offered."""

    # The Responses API rather than Chat Completions: gpt-6-sol refuses function tools on
    # Chat Completions while it reasons, which failed every conversation.
    chat_model = OpenAIResponsesModel(
        model, provider=OpenAIProvider(api_key=config.require(API_KEY_NAME))
    )
    agent = Agent(
        chat_model,
        deps_type=ConversationDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        tools=list(TOOLS),
        defer_model_check=True,
    )
    agent.output_validator(_verify_citations)
    return agent


def _verify_citations(ctx: RunContext[ConversationDeps], output: str) -> str:
    """Hold a finished answer to the standard a tool already holds a memory id to.

    A timestamp the model reconstructed reads exactly like one it retrieved, and the website
    turns each of them into a button that seeks the video, so an unchecked citation is a
    control that lies about where it goes. Rejecting one costs a whole regenerated answer,
    which is why the budget is a single retry and why an unfixable answer is stripped rather
    than refused.
    """

    unsupported = citations.unverified(output, ctx.deps.draft.spans)
    if not unsupported:
        return output
    ctx.deps.draft.text = output
    ctx.deps.draft.rejected = True
    raise ModelRetry(
        f"These citations name moments no tool returned during this answer: {', '.join(unsupported)}. "
        "Cite only timestamps that appeared in a tool result, written as [MM:SS] or "
        "[H:MM:SS], or retrieve the moment before citing it."
    )


class PydanticConversationAgentRunner:
    """Translate Pydantic AI's full event stream into the API's stable event vocabulary."""

    def __init__(self, agent: Agent[ConversationDeps, str] | None = None):
        self._agent = agent

    async def stream(
        self,
        prompt: str,
        *,
        history: Sequence[StoredMessage],
        deps: ConversationDeps,
    ) -> AsyncIterator[AgentEvent]:
        agent = self._agent or build_agent()
        try:
            async with agent.run_stream_events(
                prompt, deps=deps, message_history=_model_history(history, deps=deps)
            ) as events:
                async for event in events:
                    # Written text is collected rather than forwarded. Citations can only be
                    # checked once the answer is whole, and a rejected answer is replaced by
                    # a freshly streamed one with no signal to discard what came before, so
                    # anything forwarded early is text the reader would have to un-read.
                    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                        deps.draft.text = event.part.content or ""
                    elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        deps.draft.text += event.delta.content_delta or ""
                    elif isinstance(event, FunctionToolCallEvent):
                        yield ToolStarted(
                            call_id=event.part.tool_call_id,
                            tool=event.part.tool_name,
                            arguments=event.part.args_as_dict(raise_if_invalid=True),
                            started_at=_now(),
                        )
                    elif isinstance(event, FunctionToolResultEvent):
                        is_error = getattr(event.part, "part_kind", "") == "retry-prompt"
                        if not is_error:
                            deps.draft.record(event.part.content)
                        yield ToolFinished(
                            call_id=event.tool_call_id,
                            summary=None if is_error else _summarize_result(event.part.content),
                            finished_at=_now(),
                            error="Retrieval failed" if is_error else None,
                        )
                    elif isinstance(event, AgentRunResultEvent):
                        yield TextFragment(TypeAdapter(str).validate_python(event.result.output))
        except UnexpectedModelBehavior:
            # Only the retry budget running out on the citation check is recoverable here:
            # the answer itself is almost certainly sound and it is the citation that is
            # wrong, so it is delivered without the timestamps it could not support. Any
            # other unexpected behaviour is a real failure and stays one.
            if not deps.draft.rejected:
                raise
            yield TextFragment(deps.draft.verifiable_text())


def _model_history(
    history: Sequence[StoredMessage], *, deps: ConversationDeps | None = None
) -> list[ModelMessage]:
    """Convert only this conversation's persisted visible turns to model history."""

    # Pydantic AI assumes a supplied history already contains its system prompt. Our
    # database intentionally stores only visible user/assistant messages, so explicitly
    # reinject the fixed prompt instead of silently losing the grounding rules after turn one.
    converted: list[ModelMessage] = [
        ModelRequest(parts=[SystemPromptPart(content=SYSTEM_PROMPT)])
    ]
    if deps is not None and not deps.timestamps_reliable:
        converted.append(ModelRequest(parts=[SystemPromptPart(content=PARTIAL_TIMING_PROMPT)]))
    # Told about only where the tool is offered, so a prompt never describes a tool the model
    # cannot see.
    if deps is not None and deps.has_comments:
        converted.append(ModelRequest(parts=[SystemPromptPart(content=VIEWER_COMMENTS_PROMPT)]))
    for message in history:
        if message.role == "user":
            converted.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
        else:
            converted.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return converted


def _summarize_result(content: object) -> str:
    """Describe a returned payload without storing the potentially large raw retrieval."""

    if isinstance(content, (list, tuple)):
        return f"{len(content)} result{'s' if len(content) != 1 else ''}"
    if hasattr(content, "model_dump"):
        data = content.model_dump()
        for key in ("chapters", "memories", "segments", "matches", "findings", "comments"):
            value = data.get(key)
            if isinstance(value, list):
                return f"{len(value)} {key}"
        return type(content).__name__
    return type(content).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
