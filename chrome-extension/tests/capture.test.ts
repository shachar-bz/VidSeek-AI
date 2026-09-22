// Verify flat iframe sessions and capture bodies with a simulated Chrome debugger.
import { expect, it, vi } from "vitest";

it("captures UTF-8 captions from a child frame and excludes audio/segments/ads", async () => {
  const storage: Record<string, unknown> = {};
  let event: (source: object, method: string, params: object) => void;
  let message: (
    msg: object,
    sender: object,
    respond: (response: any) => void,
  ) => void;
  const command = vi.fn(async (_target: object, method: string) =>
    method === "Network.getResponseBody"
      ? {
          body: "WEBVTT\n\n00:00.000 --> 00:01.000\nשלום",
          base64Encoded: false,
        }
      : {},
  );
  vi.stubGlobal("chrome", {
    sidePanel: { setPanelBehavior: vi.fn(async () => {}) },
    storage: {
      session: {
        get: vi.fn(async (key: string) => ({ [key]: storage[key] })),
        set: vi.fn(async (value: object) => Object.assign(storage, value)),
        remove: vi.fn(async (key: string) => {
          delete storage[key];
        }),
      },
    },
    action: {
      setBadgeText: vi.fn(async () => {}),
      setBadgeBackgroundColor: vi.fn(async () => {}),
    },
    alarms: { clear: vi.fn(async () => {}), onAlarm: { addListener: vi.fn() } },
    downloads: { onChanged: { addListener: vi.fn() } },
    debugger: {
      attach: vi.fn(async () => {}),
      detach: vi.fn(async () => {}),
      sendCommand: command,
      onEvent: {
        addListener: (fn: typeof event) => {
          event = fn;
        },
      },
      onDetach: { addListener: vi.fn() },
    },
    scripting: { executeScript: vi.fn(async () => []) },
    runtime: {
      onMessage: {
        addListener: (fn: typeof message) => {
          message = fn;
        },
      },
    },
  });
  await import("../src/background");
  const send = (msg: object) =>
    new Promise<any>((resolve) => message(msg, {}, resolve));
  expect((await send({ type: "START_CAPTURE", tabId: 8 })).ok).toBe(true);
  event!({ tabId: 8 }, "Target.attachedToTarget", { sessionId: "child" });
  const source = { tabId: 8, sessionId: "child" };
  const urls = [
    ["https://cdn.example/movie.mp4", "video/mp4"],
    ["https://cdn.example/audio.m4s", "audio/mp4"],
    ["https://cdn.example/segment.ts", "video/mp2t"],
    ["https://gcdn.2mdn.net/ad.mp4", "video/mp4"],
    ["https://cdn.example/he.vtt", "text/vtt"],
  ];
  for (const [i, [url, mimeType]] of urls.entries()) {
    event!(source, "Network.requestWillBeSent", {
      requestId: String(i),
      request: { url, headers: {} },
      type: "Media",
    });
    event!(source, "Network.responseReceived", {
      requestId: String(i),
      response: { mimeType },
      type: "Media",
    });
    event!(source, "Network.loadingFinished", {
      requestId: String(i),
      encodedDataLength: 100,
    });
  }
  const stopped = await send({ type: "STOP_CAPTURE" });
  expect(stopped.ok).toBe(true);
  expect(stopped.candidates.map((c: any) => c.url)).toEqual([
    "https://cdn.example/movie.mp4",
  ]);
  expect(stopped.caption_candidates[0].text).toContain("שלום");
  expect(command).toHaveBeenCalledWith(
    expect.objectContaining({ sessionId: "child" }),
    "Network.enable",
    expect.any(Object),
  );
  expect(command).toHaveBeenCalledWith(
    expect.objectContaining({ sessionId: "child" }),
    "Network.getResponseBody",
    { requestId: "4" },
  );
  vi.unstubAllGlobals();
});
