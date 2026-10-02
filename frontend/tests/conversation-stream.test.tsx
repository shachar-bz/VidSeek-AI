import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationDetail, ConversationMessage, StreamEvent, ToolCallTrace, VideoDetail } from "../src/api/types";
import { chatUnavailableMessage, ConversationWorkspace } from "../src/pages/video/ConversationWorkspace";
import { applyStreamEvent, beginGeneration, endIncompleteStream } from "../src/pages/video/streamState";

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  getConversations: vi.fn(),
  renameConversation: vi.fn(),
  sendConversationMessage: vi.fn(),
  stopConversation: vi.fn()
}));
vi.mock("../src/api/conversations", () => api);
vi.mock("../src/api/video", () => ({
  getPinnedAnswers: vi.fn(async () => ({ pins: [] })),
  pinAnswer: vi.fn(),
  unpinAnswer: vi.fn()
}));

function trace(overrides: Partial<ToolCallTrace> = {}): ToolCallTrace {
  return {
    call_id: "call-1",
    tool: "memories_semantic_search",
    arguments: { query: "launch" },
    summary: null,
    started_at: "2026-09-20T10:00:00Z",
    finished_at: null,
    error: null,
    ...overrides
  };
}

describe("conversation stream state", () => {
  it("requires message_start first, appends fragments, and pairs tool results by call id", () => {
    let state = beginGeneration("What changed?", "2026-09-20T10:00:00Z");
    const events: StreamEvent[] = [
      { type: "message_start", user_message_id: "user-1", message_id: "assistant-1" },
      { type: "token", text: "It " },
      { type: "tool_call", call: trace() },
      { type: "token", text: "changed." },
      { type: "tool_result", call: trace({ summary: "3 moments found", finished_at: "2026-09-20T10:00:02Z" }) }
    ];
    for (const event of events) state = applyStreamEvent(state, event);

    expect(state.userMessage.message_id).toBe("user-1");
    expect(state.assistantMessage.message_id).toBe("assistant-1");
    expect(state.assistantMessage.content).toBe("It changed.");
    expect(state.assistantMessage.tool_trace).toHaveLength(1);
    expect(state.assistantMessage.tool_trace?.[0]?.summary).toBe("3 moments found");
  });

  it("replaces transient output with the persisted message on completion", () => {
    let state = applyStreamEvent(beginGeneration("Question"), { type: "message_start", user_message_id: "u1", message_id: "a1" });
    state = applyStreamEvent(state, { type: "token", text: "transient" });
    state = applyStreamEvent(state, { type: "message_complete", message: { message_id: "a1", role: "assistant", content: "persisted", tool_trace: null, created_at: "now", pinned: false } });
    expect(state.terminal).toBe("complete");
    expect(state.assistantMessage.content).toBe("persisted");
  });

  it("does not report success when the stream ends without a terminal event", () => {
    const started = applyStreamEvent(beginGeneration("Question"), { type: "message_start", user_message_id: "u1", message_id: "a1" });
    const ended = endIncompleteStream(started);
    expect(ended.terminal).toBe("error");
    expect(ended.error).toMatch(/ended unexpectedly/i);
  });

  it("rejects an event arriving before message_start", () => {
    const state = applyStreamEvent(beginGeneration("Question"), { type: "token", text: "bad" });
    expect(state.terminal).toBe("error");
    expect(state.assistantMessage.content).toBe("");
  });
});

describe("conversation readiness", () => {
  it("names processing stages and explains failed chat", () => {
    expect(chatUnavailableMessage("transcribing")).toMatch(/Transcribing is in progress/);
    expect(chatUnavailableMessage("failed")).toBe("Chat is unavailable because processing failed.");
    expect(chatUnavailableMessage("ready")).toBeNull();
  });

});

const video: VideoDetail = {
  video_id: "video-1",
  title: "The Water Cycle",
  custom_title: null,
  original_title: "The Water Cycle",
  source_site: "www.youtube.com",
  source_url: "https://www.youtube.com/watch?v=abc",
  duration_seconds: 600,
  tags: [],
  added_at: "2026-09-29T10:00:00Z",
  stage: "ready",
  transcript_source: "captions",
  transcript_language: "en",
  transcript_timing_fidelity: "caption",
  conversation_count: 0,
  visual_status: "ready",
  insights: null
};

const created: ConversationDetail = {
  conversation_id: "conversation-1",
  video_id: "video-1",
  title: null,
  created_at: "2026-09-29T10:00:00Z",
  updated_at: "2026-09-29T10:00:00Z",
  messages: []
};

const answer: ConversationMessage = {
  message_id: "assistant-1",
  role: "assistant",
  content: "Water evaporates in the sun.",
  tool_trace: [trace({ finished_at: "2026-09-20T10:00:02Z" })],
  created_at: "2026-09-29T10:00:00Z",
  pinned: false
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
    async push(event: StreamEvent) {
      await act(async () => {
        queue.push(event);
        wake?.();
        wake = null;
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
  };
}

function activityLine(): string | null {
  return document.querySelector(".chat-message__activity")?.textContent ?? null;
}

function typingIndicator(): Element | null {
  return document.querySelector(".chat-message__bubble--typing .chat-typing");
}

async function askQuestion(stream: ReturnType<typeof controlledStream>) {
  api.sendConversationMessage.mockImplementation(stream.events);
  render(
    <MemoryRouter initialEntries={["/videos/video-1"]}>
      <Routes>
        <Route path="/videos/:videoId" element={<ConversationWorkspace video={video} onSeek={vi.fn()} />} />
      </Routes>
    </MemoryRouter>
  );
  await screen.findByText("No chats yet.");
  fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
  fireEvent.change(screen.getByLabelText("Ask about this video"), { target: { value: "What is evaporation?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(api.sendConversationMessage).toHaveBeenCalled());
  await stream.push({ type: "message_start", user_message_id: "user-1", message_id: "assistant-1" });
}

describe("the line under a pending answer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConversations.mockResolvedValue({ conversations: [] });
    api.createConversation.mockResolvedValue(created);
    api.renameConversation.mockResolvedValue({ ...created, title: "Chat 1", message_count: 0 });
    api.getConversation.mockResolvedValue({ ...created, title: "Chat 1", messages: [] });
  });

  it("says Thinking before any call, then the label of the call running or last run", async () => {
    const stream = controlledStream();
    await askQuestion(stream);

    expect(activityLine()).toBe("Thinking…");
    expect(typingIndicator()).not.toBeNull();

    await stream.push({ type: "tool_call", call: trace({ activity: "Searching the video" }) });
    expect(activityLine()).toBe("Searching the video…");

    await stream.push({ type: "tool_result", call: trace({ activity: "Searching the video", finished_at: "2026-09-20T10:00:02Z" }) });
    expect(activityLine()).toBe("Searching the video…");

    await stream.push({ type: "tool_call", call: trace({ call_id: "call-2", tool: "get_chapter_context", activity: "Reading a chapter" }) });
    expect(activityLine()).toBe("Reading a chapter…");
  });

  it("says Thinking for a call the server gave no label", async () => {
    const stream = controlledStream();
    await askQuestion(stream);

    await stream.push({ type: "tool_call", call: trace({ tool: "a_new_tool", activity: null }) });
    expect(activityLine()).toBe("Thinking…");
  });

  it("disappears when the answer arrives, which appears whole", async () => {
    const stream = controlledStream();
    api.getConversation.mockResolvedValue({ ...created, title: "Chat 1", messages: [answer] });
    await askQuestion(stream);
    await stream.push({ type: "tool_call", call: trace({ activity: "Searching the video" }) });

    await stream.push({ type: "token", text: answer.content });
    await stream.push({ type: "message_complete", message: answer });

    await waitFor(() => expect(activityLine()).toBeNull());
    expect(typingIndicator()).toBeNull();
    expect(screen.getByText(answer.content)).toBeTruthy();
  });

  it.each([
    ["stopped", { type: "stopped", message: { ...answer, content: "Water evap" } }],
    ["error", { type: "error", message: "Unable to finish the answer." }]
  ] as const)("disappears when the answer is %s", async (_, terminal) => {
    const stream = controlledStream();
    await askQuestion(stream);
    await stream.push({ type: "tool_call", call: trace({ activity: "Searching the video" }) });

    await stream.push(terminal as StreamEvent);

    await waitFor(() => expect(activityLine()).toBeNull());
    expect(typingIndicator()).toBeNull();
  });
});
