"""The conversation contract: threads, their messages, and the stream an answer arrives on.

One conversation belongs to one user and one video, and its context is its own message
history and nothing else. That is why nothing here carries a list of other conversations or
any cross-video identifier: there is no such view, and a field for one would invite it.

The streaming half is the part both ends have to agree on exactly. An answer is delivered as
a sequence of server-sent events, each a JSON object with a `type`, and the trace of what the
agent did arrives on that same stream rather than after it -- §9 asks a slow answer to be
legible while it is slow, which only works if the tool calls are visible as they happen.
The same trace is then stored on the message, so reopening a conversation shows how each
answer was reached; `ToolCallTrace` is one shape used for both, so that a replayed
conversation and a live one render through the same code.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

MAX_MESSAGE_LENGTH = 8_000
MAX_CONVERSATION_TITLE_LENGTH = 200

# The server-sent event name every payload below is delivered under. One name for all of
# them, with the payload's own `type` discriminating: an EventSource listener per event
# type would have to be registered before the first event arrives, and the set of types is
# expected to grow.
STREAM_EVENT_NAME = "message"


class MessageRole(str, Enum):
    """Which side of a conversation said something. Matches `messages_role_known` in
    `migrations/0015_messages.sql`."""

    USER = "user"
    ASSISTANT = "assistant"


class ToolCallTrace(BaseModel):
    """One retrieval the agent performed, as both the live trace and the stored record.

    `arguments` is what the agent asked for and `summary` is a short line describing what
    came back -- "5 moments, 12:04-18:31" rather than the moments themselves. The results
    are deliberately not carried: they can be large, they are already reflected in the
    answer, and a trace exists to make the retrieval *legible*, including when it missed.
    """

    call_id: str
    tool: str
    arguments: dict = Field(default_factory=dict)
    summary: str | None = None
    # ISO 8601. Null on a call that is still running, which is how a live trace shows one
    # in progress.
    started_at: str | None = None
    finished_at: str | None = None
    # Set when the tool raised rather than answered. A retrieval that failed is part of how
    # the answer was reached and is kept rather than dropped.
    error: str | None = None


class ConversationMessage(BaseModel):
    """One turn of a conversation, as the website renders it.

    `tool_trace` is null for a user message, which called no tool, and for an assistant
    message answered without one. `pinned` is this user's own pin state for the message,
    which is why it is on the message rather than fetched separately: the conversation view
    has to show a pin toggle on every answer.
    """

    message_id: str
    role: MessageRole
    content: str
    tool_trace: list[ToolCallTrace] | None = None
    created_at: str
    pinned: bool = False


class ConversationSummary(BaseModel):
    """One conversation as it appears in the list on a video page.

    `title` is null until the first exchange generates one, which is also what a
    conversation with no messages yet looks like; the page shows a placeholder for both.
    """

    conversation_id: str
    video_id: str
    title: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0


class ConversationList(BaseModel):
    """This user's conversations about one video, most recently used first."""

    video_id: str
    conversations: list[ConversationSummary] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    """One conversation with its full message history, in the order it was said."""

    conversation_id: str
    video_id: str
    title: str | None = None
    created_at: str
    updated_at: str
    messages: list[ConversationMessage] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    """Start a new thread, optionally with the question that prompted it.

    `first_message` is what a suggested question sends: §4.4 has each one open a new
    conversation pre-filled with it. It is not sent to the agent by this request -- creating
    a conversation and answering in it stay two calls, so the client can open the thread and
    then stream the answer into it the same way it does for every other message.
    """

    first_message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)


class RenameConversationRequest(BaseModel):
    """Set a conversation's title, replacing the generated one."""

    title: str = Field(min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)


class SendMessageRequest(BaseModel):
    """One question for the agent, answered on the response's event stream.

    `current_time_seconds` is where the page's player was when the question was sent. It is
    what "this", "here" and "what's on screen now" refer to, which the words alone cannot say,
    so it travels with every message rather than being asked for. Null when the page has no
    player position to give -- the video has not loaded, or the client is not a video page.
    `player_paused` says whether the player stood still there: paused, the position is the very
    frame the viewer is asking about; playing, what they asked about may be a few seconds
    earlier. Null when the page did not say.
    """

    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    current_time_seconds: float | None = Field(default=None, ge=0)
    player_paused: bool | None = None


class StreamEventType(str, Enum):
    """Every kind of event an answer's stream carries."""

    MESSAGE_START = "message_start"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MESSAGE_COMPLETE = "message_complete"
    STOPPED = "stopped"
    ERROR = "error"


class MessageStartEvent(BaseModel):
    """The first event on every stream: both message ids, before any token arrives.

    The user's message is persisted before the agent is asked anything, so its id is known
    here; the assistant's row is created empty at the same moment so that a pin, a stop or a
    reconnect has something to name. A client that receives this and nothing else still has
    a conversation it can reopen.
    """

    type: Literal[StreamEventType.MESSAGE_START] = StreamEventType.MESSAGE_START
    user_message_id: str
    message_id: str


class TokenEvent(BaseModel):
    """One fragment of the answer, to be appended to what has arrived so far.

    A fragment, not a whole answer so far: re-sending the accumulated text on every token
    would make a long answer quadratic in what it costs to deliver.
    """

    type: Literal[StreamEventType.TOKEN] = StreamEventType.TOKEN
    text: str


class ToolCallEvent(BaseModel):
    """The agent has started a retrieval. `call_id` pairs it with its result."""

    type: Literal[StreamEventType.TOOL_CALL] = StreamEventType.TOOL_CALL
    call: ToolCallTrace


class ToolResultEvent(BaseModel):
    """A retrieval finished, carrying the same `call_id` the call announced."""

    type: Literal[StreamEventType.TOOL_RESULT] = StreamEventType.TOOL_RESULT
    call: ToolCallTrace


class MessageCompleteEvent(BaseModel):
    """The answer is finished and stored. The last event on a successful stream.

    Carries the whole message rather than only a terminator, so that a client can replace
    what it accumulated with what was actually persisted instead of trusting that its own
    concatenation matched.
    """

    type: Literal[StreamEventType.MESSAGE_COMPLETE] = StreamEventType.MESSAGE_COMPLETE
    message: ConversationMessage


class StoppedEvent(BaseModel):
    """Generation was stopped by the user. The partial answer is kept, not discarded.

    §9 asks that stopping loses the generation and not the conversation, so whatever had
    been produced is stored as the assistant's message and comes back here in full.
    """

    type: Literal[StreamEventType.STOPPED] = StreamEventType.STOPPED
    message: ConversationMessage


class ErrorEvent(BaseModel):
    """The answer could not be produced. The last event on a failed stream.

    An error arrives on the stream rather than as an HTTP status because the response has
    already begun: the status was sent before the agent was asked anything.
    """

    type: Literal[StreamEventType.ERROR] = StreamEventType.ERROR
    message: str


StreamEvent = (
    MessageStartEvent
    | TokenEvent
    | ToolCallEvent
    | ToolResultEvent
    | MessageCompleteEvent
    | StoppedEvent
    | ErrorEvent
)
