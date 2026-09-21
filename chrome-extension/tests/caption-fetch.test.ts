// Caption reads stay bounded even when servers omit content-length.
import { afterEach, expect, it, vi } from "vitest";
import { readCaptionBody } from "../src/caption-fetch";

afterEach(() => vi.unstubAllGlobals());
it("uses the existing browser session and preserves Hebrew text", async () => {
  const fetch = vi.fn(async () => new Response("WEBVTT\nשלום עולם"));
  vi.stubGlobal("fetch", fetch);
  expect(await readCaptionBody("https://course.example/transcript")).toContain(
    "שלום עולם",
  );
  expect(fetch).toHaveBeenCalledWith(
    "https://course.example/transcript",
    expect.objectContaining({
      credentials: "include",
      signal: expect.any(AbortSignal),
    }),
  );
});
it("stops a chunked oversized response", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream({
    pull(controller) {
      controller.enqueue(new Uint8Array(1_000_001));
    },
    cancel,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body)),
  );
  expect(await readCaptionBody("https://course.example/transcript")).toBeNull();
  expect(cancel).toHaveBeenCalledOnce();
});
it("treats a failed authenticated request as a missing track", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("login", { status: 403 })),
  );
  expect(await readCaptionBody("https://course.example/transcript")).toBeNull();
});
