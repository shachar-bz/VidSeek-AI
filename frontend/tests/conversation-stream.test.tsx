import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StreamEvent, ToolCallTrace } from "../src/api/types";
import { chatUnavailableMessage } from "../src/pages/video/ConversationWorkspace";
import { applyStreamEvent, beginGeneration, endIncompleteStream } from "../src/pages/video/streamState";
import { ToolTrace } from "../src/pages/video/ToolTrace";

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

describe("conversation readiness and traces", () => {
  it("names processing stages and explains failed chat", () => {
    expect(chatUnavailableMessage("transcribing")).toMatch(/Transcribing is in progress/);
    expect(chatUnavailableMessage("failed")).toBe("Chat is unavailable because processing failed.");
    expect(chatUnavailableMessage("partial")).toBeNull();
  });

  it("renders active calls and retrieval misses through the shared trace component", () => {
    render(<ToolTrace calls={[trace(), trace({ call_id: "call-2", tool: "get_video_outline", finished_at: "done" })]} />);
    expect(screen.getByText("In progress…")).toBeTruthy();
    expect(screen.getByText("No retrieval results were returned.")).toBeTruthy();
  });
});
