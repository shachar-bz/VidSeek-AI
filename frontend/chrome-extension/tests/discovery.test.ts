import { describe, expect, it } from "vitest";

import { classifyMediaUrl, chooseDirectCandidate, originPatterns } from "../src/discovery";
import type { DiscoveryResult } from "../src/types";

describe("media discovery helpers", () => {
  it("classifies direct, HLS, and DASH media", () => {
    expect(classifyMediaUrl("https://cdn.example/video.mp4")).toBe("direct");
    expect(classifyMediaUrl("https://cdn.example/master.m3u8")).toBe("hls");
    expect(classifyMediaUrl("https://cdn.example/manifest", "application/dash+xml")).toBe("dash");
    expect(classifyMediaUrl("https://cdn.example/image.jpg")).toBeNull();
  });

  it("requests only exact discovered origins", () => {
    const discovery: DiscoveryResult = {
      page_url: "https://app.example/watch/1",
      page_title: "Example",
      drm_detected: false,
      media_candidates: [
        { kind: "hls", url: "https://media.example/master.m3u8?token=secret", mime_type: "", source: "dom" }
      ],
      caption_candidates: [
        { url: "https://captions.example/en.vtt", format: "vtt", is_active: true, is_manual: true, is_visible_transcript: false }
      ]
    };
    expect(originPatterns(discovery).sort()).toEqual([
      "https://app.example/*",
      "https://captions.example/*",
      "https://media.example/*"
    ]);
  });

  it("selects a progressive file for Chrome download", () => {
    const candidate = chooseDirectCandidate([
      { kind: "direct", url: "https://cdn.example/video.webm", mime_type: "video/webm", source: "video" }
    ]);
    expect(candidate?.url).toContain("video.webm");
  });
});

