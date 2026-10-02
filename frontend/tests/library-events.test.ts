import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, writeToken } from "../src/api/client";
import { subscribeToLibraryEvents } from "../src/api/library";
import type { LibraryProgressEvent } from "../src/api/types";

function progress(jobId: string, stage: LibraryProgressEvent["stage"]): LibraryProgressEvent {
  return {
    job_id: jobId,
    video_id: null,
    stage,
    progress: stage === "ready" ? 1 : 0.5,
    status_message: stage,
    error_code: null
  };
}

/** An event-stream response that stays open until the test pushes into it or closes it. */
function openStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(
    new ReadableStream<Uint8Array>({ start: (opened) => { controller = opened; } }),
    { headers: { "Content-Type": "text/event-stream" } }
  );
  return {
    response,
    push: (event: LibraryProgressEvent) =>
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)),
    close: () => controller.close()
  };
}

/** Pull events off a subscription in the background, so the test can await what arrived. */
function collect(signal: AbortSignal) {
  const received: LibraryProgressEvent[] = [];
  const done = (async () => {
    for await (const event of subscribeToLibraryEvents(signal)) received.push(event);
  })();
  return { received, done };
}

beforeEach(() => {
  window.localStorage.clear();
  writeToken("website-token");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("library progress events", () => {
  it("shares one connection and replays the current state to a late subscriber", async () => {
    const stream = openStream();
    const fetchMock = vi.fn(() => Promise.resolve(stream.response));
    vi.stubGlobal("fetch", fetchMock);
    const lifetime = new AbortController();

    const bell = collect(lifetime.signal);
    stream.push(progress("job-1", "downloading"));
    await vi.waitFor(() => expect(bell.received).toHaveLength(1));

    const page = collect(lifetime.signal);
    stream.push(progress("job-2", "transcribing"));
    await vi.waitFor(() => expect(page.received).toHaveLength(2));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(page.received.map((event) => event.job_id)).toEqual(["job-1", "job-2"]);
    expect(bell.received.map((event) => event.job_id)).toEqual(["job-1", "job-2"]);

    lifetime.abort();
    await Promise.all([bell.done, page.done]);
  });

  it("reconnects after the stream ends and passes on only what changed meanwhile", async () => {
    vi.useFakeTimers();
    const first = openStream();
    const second = openStream();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(first.response)
      .mockResolvedValueOnce(second.response);
    vi.stubGlobal("fetch", fetchMock);
    const lifetime = new AbortController();

    const subscriber = collect(lifetime.signal);
    first.push(progress("job-1", "downloading"));
    first.close();
    await vi.waitFor(() => expect(subscriber.received).toHaveLength(1));

    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    second.push(progress("job-1", "downloading"));
    second.push(progress("job-1", "ready"));
    await vi.waitFor(() => expect(subscriber.received).toHaveLength(2));

    expect(subscriber.received.map((event) => event.stage)).toEqual(["downloading", "ready"]);

    lifetime.abort();
    await subscriber.done;
  });

  it("ends every subscription when the session is refused instead of retrying", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ detail: "Signed out" }), { status: 401 }))
    );
    vi.stubGlobal("fetch", fetchMock);

    const failure = await (async () => {
      try {
        for await (const _ of subscribeToLibraryEvents(new AbortController().signal)) {
          /* nothing arrives */
        }
      } catch (error) {
        return error;
      }
      return null;
    })();

    expect(failure).toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
