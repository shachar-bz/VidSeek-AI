import type { ConversationMessage, StreamEvent, ToolCallTrace } from "../../api/types";

export type StreamTerminal = "complete" | "stopped" | "error" | null;

export interface LiveGeneration {
  receivedStart: boolean;
  userMessage: ConversationMessage;
  assistantMessage: ConversationMessage;
  terminal: StreamTerminal;
  error: string | null;
}

export function beginGeneration(content: string, createdAt = new Date().toISOString()): LiveGeneration {
  return {
    receivedStart: false,
    userMessage: {
      message_id: "pending-user",
      role: "user",
      content,
      tool_trace: null,
      created_at: createdAt,
      pinned: false
    },
    assistantMessage: {
      message_id: "pending-assistant",
      role: "assistant",
      content: "",
      tool_trace: [],
      created_at: createdAt,
      pinned: false
    },
    terminal: null,
    error: null
  };
}

function upsertTrace(trace: ToolCallTrace[] | null, call: ToolCallTrace): ToolCallTrace[] {
  const next = [...(trace ?? [])];
  const index = next.findIndex((item) => item.call_id === call.call_id);
  if (index === -1) next.push(call);
  else next[index] = call;
  return next;
}

function protocolError(state: LiveGeneration): LiveGeneration {
  return {
    ...state,
    terminal: "error",
    error: "The answer stream ended unexpectedly. Reopen the chat to check the saved response."
  };
}

export function applyStreamEvent(state: LiveGeneration, event: StreamEvent): LiveGeneration {
  if (!state.receivedStart && event.type !== "message_start") return protocolError(state);
  if (state.receivedStart && event.type === "message_start") return protocolError(state);
  if (state.terminal) return state;

  switch (event.type) {
    case "message_start":
      return {
        ...state,
        receivedStart: true,
        userMessage: { ...state.userMessage, message_id: event.user_message_id },
        assistantMessage: { ...state.assistantMessage, message_id: event.message_id }
      };
    case "token":
      return {
        ...state,
        assistantMessage: {
          ...state.assistantMessage,
          content: state.assistantMessage.content + event.text
        }
      };
    case "tool_call":
    case "tool_result":
      return {
        ...state,
        assistantMessage: {
          ...state.assistantMessage,
          tool_trace: upsertTrace(state.assistantMessage.tool_trace, event.call)
        }
      };
    case "message_complete":
      return { ...state, assistantMessage: event.message, terminal: "complete" };
    case "stopped":
      return { ...state, assistantMessage: event.message, terminal: "stopped" };
    case "error":
      return { ...state, terminal: "error", error: event.message };
  }
}

export function endIncompleteStream(state: LiveGeneration): LiveGeneration {
  return state.terminal ? state : protocolError(state);
}
