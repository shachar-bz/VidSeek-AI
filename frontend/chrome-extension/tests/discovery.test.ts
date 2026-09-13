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

  it("strips the port, which Chrome match patterns cannot express", () => {
    const discovery: DiscoveryResult = {
      page_url: "https://app.example:8443/watch/1",
      page_title: "Example",
      drm_detected: false,
      media_candidates: [
        { kind: "direct", url: "https://cdn.example:8443/clip.mp4", mime_type: "", source: "dom" }
      ],
      caption_candidates: []
    };
    expect(originPatterns(discovery).sort()).toEqual([
      "https://app.example/*",
      "https://cdn.example/*"
    ]);
  });

  it("ignores media URLs that are not addressable by a match pattern", () => {
    const discovery: DiscoveryResult = {
      page_url: "https://app.example/watch/1",
      page_title: "Example",
      drm_detected: false,
      media_candidates: [
        { kind: "direct", url: "not a url", mime_type: "", source: "dom" },
        { kind: "direct", url: "data:video/mp4;base64,AAAA", mime_type: "", source: "dom" }
      ],
      caption_candidates: []
    };
    expect(originPatterns(discovery)).toEqual(["https://app.example/*"]);
  });

  it("selects the progressive file Chrome can download, if there is one", () => {
    expect(
      chooseDirectCandidate([
        { kind: "hls", url: "https://cdn.example/master.m3u8", mime_type: "", source: "dom" },
        { kind: "direct", url: "https://cdn.example/video.webm", mime_type: "video/webm", source: "video" }
      ])?.url
    ).toContain("video.webm");
    expect(chooseDirectCandidate([])).toBeUndefined();
    expect(
      chooseDirectCandidate([
        { kind: "hls", url: "https://cdn.example/master.m3u8", mime_type: "", source: "dom" }
      ])
    ).toBeUndefined();
  });
});

