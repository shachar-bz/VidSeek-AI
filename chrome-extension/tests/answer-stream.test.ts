// Answer streams parse into events and fold into the reply the chat shows.
import { describe, expect, it } from "vitest";

import {
  applyStreamEvent,
  beginAnswer,
  endAnswer,
  readEventStream,
} from "../src/answer-stream";
import type { ConversationMessage, StreamEvent } from "../src/types";

/** A response whose body arrives in exactly the given chunks. */
function streamedResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
  );
}

function sse(event: StreamEvent): string {
  return `event: message\ndata: ${JSON.stringify(event)}\n\n`;
}

async function collect(response: Response): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of readEventStream(response)) events.push(event);
  return events;
}

const stored: ConversationMessage = {
  message_id: "reply-1",
  role: "assistant",
  content: "It starts at [1:05].",
  tool_trace: null,
  created_at: "2026-09-24T10:00:00Z",
  pinned: false,
};

describe("reading an answer stream", () => {
  it("yields each event, even when one is split across chunks", async () => {
    const start = sse({ type: "message_start", user_message_id: "q", message_id: "r" });
    const token = sse({ type: "token", text: "Hello" });
    const events = await collect(
      streamedResponse([start.slice(0, 20), start.slice(20) + token.slice(0, 9), token.slice(9)]),
    );

    expect(events).toEqual([
      { type: "message_start", user_message_id: "q", message_id: "r" },
      { type: "token", text: "Hello" },
    ]);
  });

  it("drops events under another name and a partial event at the end", async () => {
    const events = await collect(
      streamedResponse([
        'event: progress\ndata: {"type":"token","text":"x"}\n\n',
        sse({ type: "token", text: "kept" }),
        'event: message\ndata: {"type":"tok',
      ]),
    );

    expect(events).toEqual([{ type: "token", text: "kept" }]);
  });
});

describe("folding events into the reply", () => {
  it("builds the reply from tokens and settles on the stored message", () => {
    let answer = beginAnswer("When does it start?");
    answer = applyStreamEvent(answer, { type: "message_start", user_message_id: "q-1", message_id: "reply-1" });
    answer = applyStreamEvent(answer, { type: "token", text: "It starts " });
    answer = applyStreamEvent(answer, { type: "token", text: "at 1:05" });

    expect(answer.question.message_id).toBe("q-1");
    expect(answer.reply.content).toBe("It starts at 1:05");
    expect(answer.outcome).toBeNull();

    answer = applyStreamEvent(answer, { type: "message_complete", message: stored });
    expect(answer.outcome).toBe("complete");
    expect(answer.reply).toEqual(stored);
  });

  it("keeps one trace entry per tool call as its result arrives", () => {
    const call = { call_id: "c1", tool: "memories_semantic_search", arguments: { query: "intro" } };
    let answer = applyStreamEvent(beginAnswer("q"), { type: "message_start", user_message_id: "q", message_id: "r" });
    answer = applyStreamEvent(answer, { type: "tool_call", call });
    answer = applyStreamEvent(answer, { type: "tool_result", call: { ...call, summary: "3 moments", finished_at: "t" } });

    expect(answer.reply.tool_trace).toEqual([{ ...call, summary: "3 moments", finished_at: "t" }]);
  });

  it("treats a stream that does not open with message_start as broken", () => {
    const answer = applyStreamEvent(beginAnswer("q"), { type: "token", text: "early" });

    expect(answer.outcome).toBe("error");
    expect(answer.reply.content).toBe("");
  });

  it("reports the stream's own error and ignores anything after it", () => {
    let answer = applyStreamEvent(beginAnswer("q"), { type: "message_start", user_message_id: "q", message_id: "r" });
    answer = applyStreamEvent(answer, { type: "error", message: "Unable to finish the answer." });
    answer = applyStreamEvent(answer, { type: "token", text: "late" });

    expect(answer.outcome).toBe("error");
    expect(answer.error).toBe("Unable to finish the answer.");
    expect(answer.reply.content).toBe("");
  });

  it("marks a stream that closed without a final event as an error", () => {
    const open = applyStreamEvent(beginAnswer("q"), { type: "message_start", user_message_id: "q", message_id: "r" });

    expect(endAnswer(open).outcome).toBe("error");
    const finished = applyStreamEvent(open, { type: "stopped", message: stored });
    expect(endAnswer(finished)).toBe(finished);
  });
});
