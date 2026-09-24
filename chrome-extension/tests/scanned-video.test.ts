// Each user's scan is kept apart from everyone else's and learns its video id once.
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearScannedVideo,
  readScannedVideo,
  recordScannedVideoId,
  writeScannedVideo,
} from "../src/scanned-video";
import type { ScannedVideo } from "../src/types";

function stubLocalStorage(): void {
  let items: Record<string, unknown> = {};
  vi.stubGlobal("chrome", {
    storage: {
      local: {
        get: vi.fn(async (key: string) => (key in items ? { [key]: structuredClone(items[key]) } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => {
          items = { ...items, ...structuredClone(values) };
        }),
      },
    },
  });
}

const scan = (userId: string, jobId: string): ScannedVideo => ({
  userId,
  jobId,
  jobToken: "job-token",
  title: "A talk",
  pageUrl: "https://example.com/watch",
});

describe("scanned videos", () => {
  beforeEach(stubLocalStorage);

  it("keeps one scan per user, so another account never sees it", async () => {
    await writeScannedVideo(scan("ada", "job-1"));
    await writeScannedVideo(scan("grace", "job-2"));

    expect((await readScannedVideo("ada"))?.jobId).toBe("job-1");
    expect((await readScannedVideo("grace"))?.jobId).toBe("job-2");

    await clearScannedVideo("ada");
    expect(await readScannedVideo("ada")).toBeUndefined();
    expect((await readScannedVideo("grace"))?.jobId).toBe("job-2");
  });

  it("records a job's video on the scan that job belongs to", async () => {
    await writeScannedVideo(scan("ada", "job-1"));
    await writeScannedVideo(scan("grace", "job-2"));

    await recordScannedVideoId("job-2", "video-9");
    await recordScannedVideoId("job-unknown", "video-0");

    expect((await readScannedVideo("grace"))?.videoId).toBe("video-9");
    expect((await readScannedVideo("ada"))?.videoId).toBeUndefined();
  });
});
