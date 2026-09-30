"""Conversation CRUD and cancellable SSE answer streaming."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.api.dependencies import current_user
from backend.api.routes.library import _stage, library_views
from backend.core.errors import VideoNotLinkedError
from backend.schemas.conversations import (
    STREAM_EVENT_NAME,
    ConversationDetail,
    ConversationList,
    ConversationMessage,
    ConversationSummary,
    CreateConversationRequest,
    ErrorEvent,
    MessageCompleteEvent,
    MessageStartEvent,
    RenameConversationRequest,
    SendMessageRequest,
    StoppedEvent,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
    ToolCallTrace,
    ToolResultEvent,
)
from backend.services.visual_search import VISUAL_UNAVAILABLE, visual_availability
from backend.storage.postgres import (
    PostgresComments,
    PostgresConversations,
    PostgresLibraryViews,
    PostgresMessages,
    PostgresPinnedAnswers,
    PostgresUserVideos,
    PostgresVideoRecords,
    PostgresVisualIndex,
    StoredConversation,
    StoredMessage,
    StoredUser,
)
from backend.video_agent import (
    ConversationAgentRunner,
    TextFragment,
    ToolFinished,
    ToolStarted,
)
from backend.video_agent.generation import ActiveGeneration, GenerationRegistry
from backend.video_agent.tools.deps import ConversationDeps

logger = logging.getLogger(__name__)

router = APIRouter()


def conversations_store(request: Request) -> PostgresConversations:
    return request.app.state.conversations_store


def messages_store(request: Request) -> PostgresMessages:
    return request.app.state.messages_store


def pinned_answers_store(request: Request) -> PostgresPinnedAnswers:
    return request.app.state.pinned_answers_store


def user_videos_store(request: Request) -> PostgresUserVideos:
    return request.app.state.user_videos_store


def video_records_store(request: Request) -> PostgresVideoRecords:
    return request.app.state.video_records_store


def comments_store(request: Request) -> PostgresComments:
    return request.app.state.comments_store


def visual_index_store(request: Request) -> PostgresVisualIndex:
    return request.app.state.visual_index_store


def agent_runner(request: Request) -> ConversationAgentRunner:
    return request.app.state.conversation_agent_runner


def generation_registry(request: Request) -> GenerationRegistry:
    return request.app.state.generation_registry


Conversations = Annotated[PostgresConversations, Depends(conversations_store)]
Messages = Annotated[PostgresMessages, Depends(messages_store)]
Pins = Annotated[PostgresPinnedAnswers, Depends(pinned_answers_store)]
UserVideos = Annotated[PostgresUserVideos, Depends(user_videos_store)]
LibraryViews = Annotated[PostgresLibraryViews, Depends(library_views)]
VideoRecords = Annotated[PostgresVideoRecords, Depends(video_records_store)]
Comments = Annotated[PostgresComments, Depends(comments_store)]
VisualIndex = Annotated[PostgresVisualIndex, Depends(visual_index_store)]
Runner = Annotated[ConversationAgentRunner, Depends(agent_runner)]
Generations = Annotated[GenerationRegistry, Depends(generation_registry)]
User = Annotated[StoredUser, Depends(current_user)]


@router.get("/v1/videos/{video_id}/conversations", response_model=ConversationList)
def list_conversations(
    video_id: str,
    user: User,
    conversations: Conversations,
    messages: Messages,
    user_videos: UserVideos,
) -> ConversationList:
    _require_link(user.id, video_id, user_videos)
    items = [
        _summary(item, len(messages.list_for_conversation(item.id)))
        for item in conversations.list_for_video(user.id, video_id)
    ]
    return ConversationList(video_id=video_id, conversations=items)


@router.post(
    "/v1/videos/{video_id}/conversations",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    video_id: str,
    body: CreateConversationRequest,
    user: User,
    conversations: Conversations,
    messages: Messages,
    pins: Pins,
    views: LibraryViews,
) -> ConversationDetail:
    _require_chat_capable(user.id, video_id, views)
    try:
        conversation = conversations.create(user.id, video_id)
    except VideoNotLinkedError as error:
        raise HTTPException(
            status_code=404, detail="Video is not in this user's library"
        ) from error
    if body.first_message:
        messages.add(conversation.id, "user", body.first_message)
        conversations.touch(conversation.id)
    return _detail(conversation, messages, pins)


@router.get("/v1/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    user: User,
    conversations: Conversations,
    messages: Messages,
    pins: Pins,
) -> ConversationDetail:
    conversation = _owned_conversation(conversation_id, user.id, conversations)
    return _detail(conversation, messages, pins)


@router.patch("/v1/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    user: User,
    conversations: Conversations,
    messages: Messages,
) -> ConversationSummary:
    _owned_conversation(conversation_id, user.id, conversations)
    renamed = conversations.rename(conversation_id, body.title)
    if renamed is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _summary(renamed, len(messages.list_for_conversation(conversation_id)))


@router.delete("/v1/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    user: User,
    conversations: Conversations,
) -> Response:
    _owned_conversation(conversation_id, user.id, conversations)
    conversations.delete(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    user: User,
    conversations: Conversations,
    messages: Messages,
    pins: Pins,
    views: LibraryViews,
    video_records: VideoRecords,
    comments: Comments,
    visual_index: VisualIndex,
    runner: Runner,
    generations: Generations,
) -> StreamingResponse:
    conversation = _owned_conversation(conversation_id, user.id, conversations)
    _require_chat_capable(user.id, conversation.video_id, views)
    generation = await generations.start(conversation_id)
    if generation is None:
        raise HTTPException(status_code=409, detail="An answer is already being generated")

    history = messages.list_for_conversation(conversation_id)
    try:
        user_message = messages.add(conversation_id, "user", body.content)
        assistant = messages.add(conversation_id, "assistant", "")
        conversations.touch(conversation_id)
    except Exception:
        await generations.finish(conversation_id, generation)
        raise

    events = _answer_stream(
        conversation=conversation,
        prompt=body.content,
        first_exchange=conversation.title is None
        and not any(item.role == "assistant" for item in history),
        history=history,
        user_message=user_message,
        assistant=assistant,
        runner=runner,
        generation=generation,
        generations=generations,
        conversations=conversations,
        messages=messages,
        pins=pins,
        timestamps_reliable=_timestamps_reliable(conversation.video_id, video_records),
        has_comments=comments.count(conversation.video_id) > 0,
        visual_availability=visual_availability(visual_index.state(conversation.video_id)),
        current_time_seconds=body.current_time_seconds,
        player_paused=body.player_paused,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/v1/conversations/{conversation_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_generation(
    conversation_id: str,
    user: User,
    conversations: Conversations,
    generations: Generations,
) -> dict[str, str]:
    _owned_conversation(conversation_id, user.id, conversations)
    if not await generations.request_stop(conversation_id):
        raise HTTPException(status_code=409, detail="No answer is being generated")
    return {"status": "stopping"}


async def _answer_stream(
    *,
    conversation: StoredConversation,
    prompt: str,
    first_exchange: bool,
    history: Sequence[StoredMessage],
    user_message: StoredMessage,
    assistant: StoredMessage,
    runner: ConversationAgentRunner,
    generation: ActiveGeneration,
    generations: GenerationRegistry,
    conversations: PostgresConversations,
    messages: PostgresMessages,
    pins: PostgresPinnedAnswers,
    timestamps_reliable: bool,
    has_comments: bool = False,
    visual_availability: str = VISUAL_UNAVAILABLE,
    current_time_seconds: float | None = None,
    player_paused: bool | None = None,
) -> AsyncIterator[str]:
    content = ""
    trace: list[ToolCallTrace] = []
    calls: dict[str, int] = {}
    producer: asyncio.Task | None = None
    completed = False
    yield _sse(MessageStartEvent(user_message_id=user_message.id, message_id=assistant.id))

    queue: asyncio.Queue[tuple[str, object | None]] = asyncio.Queue()
    deps = ConversationDeps(
        video_id=conversation.video_id,
        timestamps_reliable=timestamps_reliable,
        has_comments=has_comments,
        visual_availability=visual_availability,
        current_time_seconds=current_time_seconds,
        player_paused=player_paused,
        pool=getattr(messages, "_pool", None),
    )

    def delivered() -> str:
        """The answer to keep, whether or not the run got to finish one.

        A checked answer arrives whole and becomes `content`. Until it does there is nothing
        to show but the draft the agent was still writing, and no chance to ask it to fix a
        citation, so the draft is handed back with only the citations it can support.
        """
        return content or deps.draft.verifiable_text()

    async def produce() -> None:
        try:
            async for event in runner.stream(prompt, history=history, deps=deps):
                await queue.put(("event", event))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("Conversation agent failed to answer")
            await queue.put(("error", error))
        finally:
            await queue.put(("done", None))

    producer = asyncio.create_task(produce())
    try:
        while True:
            item_task = asyncio.create_task(queue.get())
            stop_task = asyncio.create_task(generation.stop_requested.wait())
            done, _ = await asyncio.wait(
                {item_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done and generation.stop_requested.is_set():
                item_task.cancel()
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer
                kept = delivered()
                persisted = await _finalize(
                    generation, assistant.id, kept, trace, messages
                )
                _maybe_title(first_exchange, conversation, prompt, kept, conversations)
                completed = True
                yield _sse(StoppedEvent(message=_message(persisted, pinned=False)))
                return

            stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task
            kind, payload = item_task.result()
            if kind == "event":
                if isinstance(payload, TextFragment):
                    content += payload.text
                    yield _sse(TokenEvent(text=payload.text))
                elif isinstance(payload, ToolStarted):
                    call = ToolCallTrace(
                        call_id=payload.call_id,
                        tool=payload.tool,
                        arguments=payload.arguments,
                        started_at=payload.started_at,
                        activity=payload.activity,
                    )
                    calls[payload.call_id] = len(trace)
                    trace.append(call)
                    yield _sse(ToolCallEvent(call=call))
                elif isinstance(payload, ToolFinished):
                    index = calls.get(payload.call_id)
                    if index is None:
                        continue
                    trace[index] = trace[index].model_copy(
                        update={
                            "summary": payload.summary,
                            "finished_at": payload.finished_at,
                            "error": payload.error,
                        }
                    )
                    yield _sse(ToolResultEvent(call=trace[index]))
            elif kind == "error":
                kept = delivered()
                await _finalize(generation, assistant.id, kept, trace, messages)
                _maybe_title(first_exchange, conversation, prompt, kept, conversations)
                completed = True
                yield _sse(ErrorEvent(message="Unable to finish the answer."))
                return
            elif kind == "done":
                persisted = await _finalize(
                    generation, assistant.id, content, trace, messages
                )
                _maybe_title(first_exchange, conversation, prompt, content, conversations)
                completed = True
                yield _sse(MessageCompleteEvent(message=_message(persisted, pinned=False)))
                return
    finally:
        if producer is not None and not producer.done():
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
        if not completed:
            kept = delivered()
            await _finalize(generation, assistant.id, kept, trace, messages)
            _maybe_title(first_exchange, conversation, prompt, kept, conversations)
        await generations.finish(conversation.id, generation)


async def _finalize(
    generation: ActiveGeneration,
    message_id: str,
    content: str,
    trace: Sequence[ToolCallTrace],
    messages: PostgresMessages,
) -> StoredMessage:
    async with generation.finalize_lock:
        if not generation.finalized:
            stored = messages.update_assistant(
                message_id,
                content,
                # The activity label is only for display while waiting, so it is not kept.
                [call.model_dump(mode="json", exclude={"activity"}) for call in trace] or None,
            )
            if stored is None:
                raise RuntimeError("Assistant message disappeared during generation")
            generation.finalized = True
            return stored
        stored = messages.get(message_id)
        if stored is None:
            raise RuntimeError("Assistant message disappeared during generation")
        return stored


def _require_link(user_id: str, video_id: str, user_videos: PostgresUserVideos) -> None:
    if user_videos.get(user_id, video_id) is None:
        raise HTTPException(status_code=404, detail="Video not found")


def _require_chat_capable(
    user_id: str,
    video_id: str,
    views: PostgresLibraryViews,
) -> None:
    row = views.get_video(user_id, video_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if not _stage(row).allows_chat:
        raise HTTPException(status_code=409, detail="Video is not ready for chat")


def _timestamps_reliable(video_id: str, video_records: PostgresVideoRecords) -> bool:
    record = video_records.get_by_id(video_id)
    if record is None:
        # Nothing is known about the timing, which is not the same as knowing there is none.
        return True
    return bool(record.video.transcript_timing_fidelity)


def _owned_conversation(
    conversation_id: str,
    user_id: str,
    conversations: PostgresConversations,
) -> StoredConversation:
    conversation = conversations.get(conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _summary(conversation: StoredConversation, message_count: int) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=conversation.id,
        video_id=conversation.video_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
    )


def _detail(
    conversation: StoredConversation,
    messages: PostgresMessages,
    pins: PostgresPinnedAnswers,
) -> ConversationDetail:
    pinned_ids = {
        pin.message_id
        for pin in pins.list_for_video(conversation.user_id, conversation.video_id)
    }
    return ConversationDetail(
        conversation_id=conversation.id,
        video_id=conversation.video_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            _message(item, pinned=item.id in pinned_ids)
            for item in messages.list_for_conversation(conversation.id)
        ],
    )


def _message(message: StoredMessage, *, pinned: bool) -> ConversationMessage:
    trace = None
    if message.tool_trace:
        trace = [ToolCallTrace.model_validate(item) for item in message.tool_trace]
    return ConversationMessage(
        message_id=message.id,
        role=message.role,
        content=message.content,
        tool_trace=trace,
        created_at=message.created_at,
        pinned=pinned,
    )


def _maybe_title(
    first_exchange: bool,
    conversation: StoredConversation,
    prompt: str,
    answer: str,
    conversations: PostgresConversations,
) -> None:
    if not first_exchange or conversation.title is not None:
        return
    title_source = prompt.strip() or answer.strip()
    title = " ".join(title_source.split())[:80].rstrip()
    if title:
        conversations.rename(conversation.id, title)


def _sse(event: StreamEvent) -> str:
    return f"event: {STREAM_EVENT_NAME}\ndata: {event.model_dump_json()}\n\n"
