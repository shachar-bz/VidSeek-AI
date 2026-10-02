"""Model-backed agent runner and its provider-independent streaming events."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic_ai import (
    Agent,
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
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.core import config
from backend.services.visual_search import VISUAL_PROCESSING, VISUAL_READY
from backend.storage.postgres import StoredMessage

from . import citations
from .activity import tool_activity
from .prompt import (
    SYSTEM_PROMPT,
    VISUAL_PROCESSING_PROMPT,
    VISUAL_PROMPT,
    VISUAL_UNAVAILABLE_PROMPT,
    viewer_position_prompt,
)
from .tools.deps import ConversationDeps
from .tools.get_chapter_context import get_chapter_context
from .tools.get_memory_context import get_memory_context
from .tools.get_video_info import get_video_info
from .tools.get_video_outline import get_video_outline
from .tools.get_viewer_comments import viewer_comments_tool
from .tools.memories_semantic_search import memories_semantic_search
from .tools.visual_tools import VISUAL_TOOLS

# Every other OpenAI call site in the backend (video_insights, grouper, segmenter,
# transcriber) reads this same key explicitly; pydantic_ai's default OpenAI provider
# looks for the standard OPENAI_API_KEY instead, which this project never sets.
API_KEY_NAME = "OPENAI_API_KEY_DUDU"
MODEL_NAME = "gpt-6.1-sol"
PARAGRAPH_BREAK = "\n\n"
PARTIAL_TIMING_PROMPT = (
    "The current video's transcript has no timing data, so the moments you retrieve carry no "
    "reliable timestamps. Do not give timestamps or time ranges; tell the user they are "
    "unavailable for this video, and still answer from the retrieved video content."
)
TOOLS = (
    get_video_info,
    get_video_outline,
    memories_semantic_search,
    get_chapter_context,
    get_memory_context,
    # Offered only for a video whose visual index is ready; see `tools/visual_tools.py`.
    *VISUAL_TOOLS,
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

    @property
    def activity(self) -> str | None:
        """What the call is doing, in words, for the line under a pending answer."""

        return tool_activity(self.tool)


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
    """Build the production agent: five transcript tools, the five visual tools a video with a
    ready visual index is offered, and the comments tool a YouTube video with stored comments is
    offered."""

    # The Responses API rather than Chat Completions: gpt-6.1-sol refuses function tools on
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
    return agent


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
        # Citations are checked one at a time as they close, so the answer can be forwarded as
        # it is written. A citation no tool backs is dropped instead of sending the whole answer
        # back to be rewritten, which would leave the reader with text they would have to unread.
        citation_filter = citations.CitationFilter(deps.retrieved.spans)
        shown_any = False

        async with agent.run_stream_events(
            prompt, deps=deps, message_history=_model_history(history, deps=deps)
        ) as events:
            async for event in events:
                written: str | None = None
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    # Text a model writes before calling a tool, and again once the tool has
                    # answered, would run together as one sentence without this break.
                    written = (PARAGRAPH_BREAK if shown_any else "") + citation_filter.feed(
                        event.part.content or ""
                    )
                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    written = citation_filter.feed(event.delta.content_delta or "")
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
                        deps.retrieved.record(event.part.content)
                    yield ToolFinished(
                        call_id=event.tool_call_id,
                        summary=None if is_error else _summarize_result(event.part.content),
                        finished_at=_now(),
                        error="Retrieval failed" if is_error else None,
                    )
                if written:
                    shown_any = True
                    yield TextFragment(written)
        tail = citation_filter.finish()
        if tail:
            yield TextFragment(tail)


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
    # The visual tools are offered only for a ready index, so the full section goes with them
    # and the other two say what to tell the user instead of looking.
    if deps is not None:
        converted.append(ModelRequest(parts=[SystemPromptPart(content=_visual_prompt(deps))]))
    for message in history:
        if message.role == "user":
            converted.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
        else:
            converted.append(ModelResponse(parts=[TextPart(content=message.content)]))
    # After the history, right before the question it belongs to: the position is this
    # question's, and an earlier turn's player may have been somewhere else. Rebuilt every turn
    # and never stored, like everything else here but the visible messages.
    if deps is not None:
        position = viewer_position_prompt(deps.current_time_seconds, deps.player_paused)
        converted.append(ModelRequest(parts=[SystemPromptPart(content=position)]))
    return converted


def _visual_prompt(deps: ConversationDeps) -> str:
    """The visual section for this video: how to look, or what to say while it cannot be looked at."""

    if deps.visual_availability == VISUAL_READY:
        return VISUAL_PROMPT
    if deps.visual_availability == VISUAL_PROCESSING:
        return VISUAL_PROCESSING_PROMPT
    return VISUAL_UNAVAILABLE_PROMPT


def _summarize_result(content: object) -> str:
    """Describe a returned payload without storing the potentially large raw retrieval."""

    if isinstance(content, (list, tuple)):
        return f"{len(content)} result{'s' if len(content) != 1 else ''}"
    if hasattr(content, "model_dump"):
        data = content.model_dump()
        for key in ("chapters", "memories", "segments", "matches", "moments", "frames", "comments"):
            value = data.get(key)
            if isinstance(value, list):
                return f"{len(value)} {key}"
        return type(content).__name__
    return type(content).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
