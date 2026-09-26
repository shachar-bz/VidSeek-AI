// Frame inspection requests main-page access and preserves actionable failures.
import { afterEach, expect, it, vi } from "vitest";
import { inspectFrames } from "../src/frame-discovery";
import { discoverDomTranscript } from "../src/dom-transcript";

afterEach(() => vi.unstubAllGlobals());

function setup(frames = [{ frameId: 0, url: "https://archive.org/details/video" }]) {
  const request = vi.fn().mockResolvedValue(true);
  const executeScript = vi.fn().mockResolvedValue([{ frameId: 0, result: {
    page_url: frames[0]?.url, media_candidates: [], caption_candidates: [],
  } }]);
  vi.stubGlobal("chrome", {
    webNavigation: { getAllFrames: vi.fn().mockResolvedValue(frames) },
    permissions: { request },
    scripting: { executeScript },
  });
  return { request, executeScript };
}

it("requests the top-level origin even when the page has no iframe", async () => {
  const { request, executeScript } = setup();
  await inspectFrames(42, true);
  expect(request).toHaveBeenCalledWith({ origins: ["https://archive.org/*"] });
  expect(request.mock.invocationCallOrder[0]).toBeLessThan(executeScript.mock.invocationCallOrder[0]!);
});

it("deduplicates frame origins and ignores non-web frames", async () => {
  const { request } = setup([
    { frameId: 0, url: "https://archive.org/details/video" },
    { frameId: 1, url: "https://archive.org/embed/video" },
    { frameId: 2, url: "https://player.example:8443/video" },
    { frameId: 3, url: "about:blank" },
  ]);
  await inspectFrames(42, true);
  expect(request).toHaveBeenCalledWith({ origins: ["https://archive.org/*", "https://player.example/*"] });
});

it("does not prompt during playback verification", async () => {
  const { request } = setup();
  await inspectFrames(42);
  expect(request).not.toHaveBeenCalled();
});

it("surfaces Chrome's error when inspection fails", async () => {
  const { executeScript } = setup();
  executeScript.mockRejectedValue(new Error("Cannot access contents of the page"));
  await expect(inspectFrames(42, true)).rejects.toThrow("Frame 0: Cannot access contents of the page");
});

it("keeps a successful page result when a sibling frame fails", async () => {
  const { executeScript } = setup([
    { frameId: 0, url: "https://archive.org/details/video" },
    { frameId: 1, url: "https://player.example/video" },
  ]);
  executeScript.mockRejectedValueOnce(new Error("Frame unloaded"));
  expect(await inspectFrames(42)).toHaveLength(1);
});

it("explains an empty frame enumeration", async () => {
  setup([]);
  await expect(inspectFrames(42)).rejects.toThrow("no page frame returned a result");
});

it("attaches generic timed DOM captions to the sole video's request", async () => {
  const { executeScript } = setup();
  const owner = { page_url: "https://example.test/watch", media_candidates: [], caption_candidates: [] };
  const caption = { format: "json", text: '{"unit":"seconds","cues":[]}' };
  executeScript.mockResolvedValueOnce([{ frameId: 0, result: { ...owner, videos: [owner] } }])
    .mockResolvedValueOnce([{ frameId: 0, result: [caption] }]);
  const found = await inspectFrames(42);
  expect(executeScript).toHaveBeenLastCalledWith({ target: { tabId: 42, frameIds: [0] }, func: discoverDomTranscript, args: [owner.page_url] });
  expect(found[0]!.result!.caption_candidates).toEqual([caption]);
  expect(found[0]!.result!.videos![0]!.caption_candidates).toEqual([caption]);
});

it("keeps discovered media when the DOM collector loses frame access", async () => {
  const { executeScript } = setup();
  const owner = { page_url: "https://example.test/watch", media_candidates: [], caption_candidates: [] };
  executeScript.mockResolvedValueOnce([{ frameId: 0, result: { ...owner, videos: [owner] } }])
    .mockRejectedValueOnce(new Error("Frame unloaded"));
  expect(await inspectFrames(42)).toHaveLength(1);
});

it("does not assign a page transcript to multiple videos", async () => {
  const { executeScript } = setup();
  const owner = { media_candidates: [], caption_candidates: [] };
  executeScript.mockResolvedValueOnce([{ frameId: 0, result: { ...owner, videos: [owner, { ...owner }] } }]);
  await inspectFrames(42);
  expect(executeScript).toHaveBeenCalledTimes(1);
});
