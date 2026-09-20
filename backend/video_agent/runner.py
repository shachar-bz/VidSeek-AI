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
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from backend.storage.postgres import StoredMessage

from .prompt import SYSTEM_PROMPT
from .tools.deps import ConversationDeps
from .tools.get_chapter_context import get_chapter_context
from .tools.get_memory_context import get_memory_context
from .tools.get_video_info import get_video_info
from .tools.get_video_outline import get_video_outline
from .tools.memories_semantic_search import memories_semantic_search

MODEL_NAME = "openai:gpt-5.6-terra"
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
    """Build the production agent with exactly the five video-scoped retrieval tools."""

    return Agent(
        model,
        deps_type=ConversationDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        tools=list(TOOLS),
        defer_model_check=True,
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
        async with agent.run_stream_events(
            prompt, deps=deps, message_history=_model_history(history, deps=deps)
        ) as events:
            async for event in events:
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    if event.part.content:
                        yield TextFragment(event.part.content)
                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    if event.delta.content_delta:
                        yield TextFragment(event.delta.content_delta)
                elif isinstance(event, FunctionToolCallEvent):
                    yield ToolStarted(
                        call_id=event.part.tool_call_id,
                        tool=event.part.tool_name,
                        arguments=event.part.args_as_dict(raise_if_invalid=True),
                        started_at=_now(),
                    )
                elif isinstance(event, FunctionToolResultEvent):
                    is_error = getattr(event.part, "part_kind", "") == "retry-prompt"
                    yield ToolFinished(
                        call_id=event.tool_call_id,
                        summary=None if is_error else _summarize_result(event.part.content),
                        finished_at=_now(),
                        error="Retrieval failed" if is_error else None,
                    )
                elif isinstance(event, AgentRunResultEvent):
                    TypeAdapter(str).validate_python(event.result.output)


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
        for key in ("chapters", "memories", "segments", "matches"):
            value = data.get(key)
            if isinstance(value, list):
                return f"{len(value)} {key}"
        return type(content).__name__
    return type(content).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
