// Reads an answer's server-sent event stream and folds its events into the reply being shown.
import { STREAM_EVENT_NAME } from "./types";
import type { ConversationMessage, StreamEvent, ToolCallTrace } from "./types";

/**
 * Yields each payload of one event stream as it arrives.
 *
 * Read off a `fetch` body rather than through `EventSource`, which can neither POST a
 * question nor send an `Authorization` header. Events are separated by a blank line and carry
 * an `event:` name and `data:` lines; a partial event left when the stream ends is dropped.
 */
export async function* readEventStream(
  response: Response,
): AsyncGenerator<StreamEvent> {
  const body = response.body;
  if (!body) return;
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const parsed = parseEvent(buffer.slice(0, boundary));
        if (parsed) yield parsed;
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

function parseEvent(block: string): StreamEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice("event:".length).trim();
    else if (line.startsWith("data:"))
      data.push(line.slice("data:".length).trimStart());
  }
  if ((name || STREAM_EVENT_NAME) !== STREAM_EVENT_NAME || !data.length)
    return null;
  try {
    return JSON.parse(data.join("\n")) as StreamEvent;
  } catch {
    return null;
  }
}

export type AnswerOutcome = "complete" | "stopped" | "error" | null;

/** The question just asked and the reply it is getting, while the reply streams in. */
export interface LiveAnswer {
  question: ConversationMessage;
  reply: ConversationMessage;
  started: boolean;
  outcome: AnswerOutcome;
  error: string | null;
}

export function beginAnswer(
  content: string,
  createdAt = new Date().toISOString(),
): LiveAnswer {
  return {
    question: {
      message_id: "pending-question",
      role: "user",
      content,
      tool_trace: null,
      created_at: createdAt,
      pinned: false,
    },
    reply: {
      message_id: "pending-reply",
      role: "assistant",
      content: "",
      tool_trace: [],
      created_at: createdAt,
      pinned: false,
    },
    started: false,
    outcome: null,
    error: null,
  };
}

const BROKEN_STREAM =
  "The answer stopped arriving. Reopen the chat to see what was saved.";

function upsertTrace(
  trace: ToolCallTrace[] | null | undefined,
  call: ToolCallTrace,
): ToolCallTrace[] {
  const next = [...(trace ?? [])];
  const index = next.findIndex((item) => item.call_id === call.call_id);
  if (index === -1) next.push(call);
  else next[index] = call;
  return next;
}

/** Applies one stream event. Anything out of order ends the answer as an error. */
export function applyStreamEvent(
  answer: LiveAnswer,
  event: StreamEvent,
): LiveAnswer {
  if (answer.outcome) return answer;
  if (answer.started === (event.type === "message_start"))
    return { ...answer, outcome: "error", error: BROKEN_STREAM };
  switch (event.type) {
    case "message_start":
      return {
        ...answer,
        started: true,
        question: { ...answer.question, message_id: event.user_message_id },
        reply: { ...answer.reply, message_id: event.message_id },
      };
    case "token":
      return {
        ...answer,
        reply: { ...answer.reply, content: answer.reply.content + event.text },
      };
    case "tool_call":
    case "tool_result":
      return {
        ...answer,
        reply: {
          ...answer.reply,
          tool_trace: upsertTrace(answer.reply.tool_trace, event.call),
        },
      };
    case "message_complete":
      return { ...answer, reply: event.message, outcome: "complete" };
    case "stopped":
      return { ...answer, reply: event.message, outcome: "stopped" };
    case "error":
      return { ...answer, outcome: "error", error: event.message };
  }
}

/** A stream that closed without a final event did not finish its answer. */
export function endAnswer(answer: LiveAnswer): LiveAnswer {
  return answer.outcome
    ? answer
    : { ...answer, outcome: "error", error: BROKEN_STREAM };
}
