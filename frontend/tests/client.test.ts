// Tests for the API client's three pieces of real logic: the query string it builds, the
// two error shapes it has to read, and the event stream it parses.

import { describe, expect, it } from "vitest";

import { buildQuery, describeDetail, readEventStream } from "../src/api/client";
import { STREAM_EVENT_NAME, type StreamEvent } from "../src/api/types";

describe("buildQuery", () => {
  it("drops values the API should not be asked about at all", () => {
    // An absent filter and an empty search box are the same request as no filter, and
    // sending `search=` would make the API decide what an empty search means.
    expect(buildQuery({ search: "", stage: undefined, tag: null })).toBe("");
  });

  it("repeats a key for each element rather than joining them", () => {
    // `tags` narrows: every tag must match, which only works if each arrives separately.
    expect(buildQuery({ tags: ["work", "python"] })).toBe("?tags=work&tags=python");
  });

  it("encodes values that would otherwise change the query's shape", () => {
    expect(buildQuery({ search: "a&b=c" })).toBe("?search=a%26b%3Dc");
  });

  it("is empty for no parameters at all", () => {
    expect(buildQuery(undefined)).toBe("");
  });
});

describe("describeDetail", () => {
  it("reads a policy error, which the API sends as one sentence", () => {
    expect(describeDetail("Extension origin is not allowed")).toBe(
      "Extension origin is not allowed"
    );
  });

  it("reads a validation error, which the API sends as a list of fields", () => {
    // The shape `api/app.py`'s redact_validation_errors builds.
    const detail = [
      { location: ["body", "password"], message: "String should have at least 8 characters" },
      { location: ["body", "email"], message: "value is not a valid email address" }
    ];

    expect(describeDetail(detail)).toBe(
      "body.password: String should have at least 8 characters; " +
        "body.email: value is not a valid email address"
    );
  });

  it("says nothing rather than guessing when the body is a shape it does not know", () => {
    expect(describeDetail({ unexpected: true })).toBe("");
    expect(describeDetail(undefined)).toBe("");
  });
});

/** A Response whose body streams `chunks` exactly as written, boundaries included. */
function streamingResponse(chunks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    }
  });
  return new Response(body);
}

function frame(event: StreamEvent): string {
  return `event: ${STREAM_EVENT_NAME}\ndata: ${JSON.stringify(event)}\n\n`;
}

async function collect(response: Response): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of readEventStream(response)) events.push(event);
  return events;
}

describe("readEventStream", () => {
  it("treats a missing event field as the SSE default message event", async () => {
    const response = streamingResponse([
      `data: ${JSON.stringify({ type: "token", text: "default" })}\n\n`
    ]);

    expect(await collect(response)).toEqual([{ type: "token", text: "default" }]);
  });

  it("yields each event in the order it was sent", async () => {
    const sent: StreamEvent[] = [
      { type: "message_start", user_message_id: "u1", message_id: "a1" },
      { type: "token", text: "Hello" },
      { type: "token", text: " there" }
    ];

    const events = await collect(streamingResponse(sent.map(frame)));

    expect(events).toEqual(sent);
  });

  it("reassembles an event split across chunk boundaries", async () => {
    // The network decides where a chunk ends, not the sender, so an event arriving in two
    // pieces is ordinary rather than exceptional.
    const whole = frame({ type: "token", text: "split" });
    const events = await collect(
      streamingResponse([whole.slice(0, 12), whole.slice(12, 25), whole.slice(25)])
    );

    expect(events).toEqual([{ type: "token", text: "split" }]);
  });

  it("yields several events arriving in one chunk", async () => {
    const chunk = frame({ type: "token", text: "a" }) + frame({ type: "token", text: "b" });

    expect(await collect(streamingResponse([chunk]))).toHaveLength(2);
  });

  it("discards a truncated event rather than guessing at it", async () => {
    // A connection that drops mid-event must not produce half a message.
    const events = await collect(
      streamingResponse([frame({ type: "token", text: "kept" }), "event: message\ndata: {\"ty"])
    );

    expect(events).toEqual([{ type: "token", text: "kept" }]);
  });

  it("ignores a comment or keep-alive that is not one of this stream's events", async () => {
    const events = await collect(
      streamingResponse([": keep-alive\n\n", frame({ type: "token", text: "real" })])
    );

    expect(events).toEqual([{ type: "token", text: "real" }]);
  });

  it("is empty for a response with no body at all", async () => {
    expect(await collect(new Response(null))).toEqual([]);
  });
});
