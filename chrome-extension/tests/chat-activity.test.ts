// While an answer is being generated, the chat shows what the agent is doing, in the server's words.
// @vitest-environment jsdom
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationDetail,
  ConversationMessage,
  StreamEvent,
  ToolCallTrace,
  VideoDetail,
} from "../src/types";

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  renameConversation: vi.fn(),
  sendConversationMessage: vi.fn(),
  stopConversation: vi.fn(),
}));
vi.mock("../src/api", () => api);
vi.mock("../src/tab-player", () => ({
  readPlayerPosition: vi.fn(async () => null),
  seekPlayer: vi.fn(async () => true),
}));

const video = {
  video_id: "video-1",
  title: "The Water Cycle",
  source_site: "www.youtube.com",
  source_url: "https://www.youtube.com/watch?v=abc",
  stage: "ready",
  insights: null,
  conversation_count: 1,
} as unknown as VideoDetail;

const conversation: ConversationDetail = {
  conversation_id: "conversation-1",
  video_id: "video-1",
  title: "Chat 1",
  created_at: "2026-09-29T10:00:00Z",
  updated_at: "2026-09-29T10:00:00Z",
  messages: [],
};

function call(overrides: Partial<ToolCallTrace> = {}): ToolCallTrace {
  return {
    call_id: "call-1",
    tool: "memories_semantic_search",
    arguments: { query: "evaporation" },
    started_at: "2026-09-29T10:00:01Z",
    finished_at: null,
    activity: "Searching the video",
    ...overrides,
  };
}

const answer: ConversationMessage = {
  message_id: "reply-1",
  role: "assistant",
  content: "Water evaporates in the sun.",
  tool_trace: [call({ finished_at: "2026-09-29T10:00:02Z", activity: null })],
  created_at: "2026-09-29T10:00:00Z",
  pinned: false,
};

/** An answer stream the test feeds one event at a time. */
function controlledStream() {
  const queue: StreamEvent[] = [];
  let wake: (() => void) | null = null;
  async function* events(): AsyncGenerator<StreamEvent> {
    for (;;) {
      while (queue.length) yield queue.shift()!;
      await new Promise<void>((resolve) => (wake = resolve));
    }
  }
  return {
    events,
    push(event: StreamEvent) {
      queue.push(event);
      wake?.();
      wake = null;
    },
  };
}

let chat: typeof import("../src/chat");

function activityLine(): string | null {
  return document.querySelector(".chat-message__activity")?.textContent ?? null;
}

function typingIndicator(): Element | null {
  return document.querySelector(".chat-message__bubble--typing .chat-typing");
}

async function askQuestion(stream: ReturnType<typeof controlledStream>) {
  api.sendConversationMessage.mockImplementation(stream.events);
  await chat.openChat("token", video);
  const input = document.querySelector<HTMLTextAreaElement>("#chat-input")!;
  input.value = "What is evaporation?";
  document.querySelector("#chat-composer")!.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(api.sendConversationMessage).toHaveBeenCalled());
  stream.push({ type: "message_start", user_message_id: "question-1", message_id: "reply-1" });
}

beforeAll(async () => {
  document.body.innerHTML = `
    <h1 id="chat-title"></h1><p id="chat-source"></p>
    <div id="chat-messages"></div><p id="chat-notice"></p>
    <form id="chat-composer"><textarea id="chat-input"></textarea>
      <button id="chat-send" type="submit"></button><button id="chat-stop" type="button"></button>
    </form>
    <button id="chat-new" type="button"></button>`;
  chat = await import("../src/chat");
});

beforeEach(() => {
  vi.clearAllMocks();
  api.listConversations.mockResolvedValue({ conversations: [conversation] });
  api.getConversation.mockResolvedValue(structuredClone(conversation));
});

describe("the line under a pending answer", () => {
  it("says Thinking before any call, then the label of the call running or last run", async () => {
    const stream = controlledStream();
    await askQuestion(stream);

    await vi.waitFor(() => expect(activityLine()).toBe("Thinking…"));
    expect(typingIndicator()).not.toBeNull();

    stream.push({ type: "tool_call", call: call() });
    await vi.waitFor(() => expect(activityLine()).toBe("Searching the video…"));

    stream.push({ type: "tool_result", call: call({ finished_at: "2026-09-29T10:00:02Z" }) });
    stream.push({
      type: "tool_call",
      call: call({ call_id: "call-2", tool: "get_chapter_context", activity: "Reading a chapter" }),
    });
    await vi.waitFor(() => expect(activityLine()).toBe("Reading a chapter…"));
  });

  it("says Thinking for a call the server gave no label", async () => {
    const stream = controlledStream();
    await askQuestion(stream);

    stream.push({ type: "tool_call", call: call({ tool: "a_new_tool", activity: null }) });
    await vi.waitFor(() => expect(document.querySelector(".chat-message__activity")).not.toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(activityLine()).toBe("Thinking…");
  });

  it("disappears when the answer arrives, which appears whole", async () => {
    const stream = controlledStream();
    await askQuestion(stream);
    stream.push({ type: "tool_call", call: call() });
    await vi.waitFor(() => expect(activityLine()).toBe("Searching the video…"));

    stream.push({ type: "token", text: answer.content });
    stream.push({ type: "message_complete", message: answer });

    await vi.waitFor(() => expect(activityLine()).toBeNull());
    expect(typingIndicator()).toBeNull();
    expect(document.querySelector(".chat-message--assistant")?.textContent).toBe(answer.content);
  });

  it.each([
    ["stopped", { type: "stopped", message: { ...answer, content: "Water evap" } }],
    ["error", { type: "error", message: "Unable to finish the answer." }],
  ] as const)("disappears when the answer is %s", async (_, terminal) => {
    const stream = controlledStream();
    await askQuestion(stream);
    stream.push({ type: "tool_call", call: call() });
    await vi.waitFor(() => expect(activityLine()).toBe("Searching the video…"));

    stream.push(terminal as StreamEvent);

    await vi.waitFor(() => expect(activityLine()).toBeNull());
    expect(typingIndicator()).toBeNull();
  });
});
