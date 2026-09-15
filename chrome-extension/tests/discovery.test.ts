import { describe, expect, it } from "vitest";

import {
  classifyMediaUrl,
  chooseDirectCandidate,
  detectManifestDrm,
  isLicenseTraffic,
  mergeDiscoveryResults,
  originPatterns
} from "../src/discovery";
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

describe("detectManifestDrm", () => {
  it("clears a plain HLS playlist with no encryption", () => {
    const playlist = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow.m3u8\n";
    expect(detectManifestDrm(playlist, "hls")).toEqual({ drm_detected: false });
  });

  it("clears HLS AES-128, which yt-dlp already decrypts on its own", () => {
    const playlist = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:10,\nseg1.ts\n';
    expect(detectManifestDrm(playlist, "hls")).toEqual({ drm_detected: false });
  });

  it("flags HLS SAMPLE-AES with a Widevine keyformat", () => {
    const playlist =
      '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",URI="skd://x"\n';
    const check = detectManifestDrm(playlist, "hls");
    expect(check.drm_detected).toBe(true);
    expect(check.system).toBe("widevine");
  });

  it("flags HLS FairPlay by its keyformat", () => {
    const playlist =
      '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,KEYFORMAT="com.apple.streamingkeydelivery",URI="skd://x"\n';
    expect(detectManifestDrm(playlist, "hls").system).toBe("fairplay");
  });

  it("clears a DASH manifest with no ContentProtection", () => {
    const manifest = '<MPD><Period><AdaptationSet mimeType="video/mp4"></AdaptationSet></Period></MPD>';
    expect(detectManifestDrm(manifest, "dash")).toEqual({ drm_detected: false });
  });

  it("flags a DASH manifest that declares Widevine ContentProtection", () => {
    const manifest =
      '<MPD><Period><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/></AdaptationSet></Period></MPD>';
    const check = detectManifestDrm(manifest, "dash");
    expect(check.drm_detected).toBe(true);
    expect(check.system).toBe("widevine");
  });

  it("flags an unrecognized ContentProtection scheme as generic DRM", () => {
    const manifest = '<MPD><ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011"/></MPD>';
    expect(detectManifestDrm(manifest, "dash")).toEqual({
      drm_detected: true,
      system: "drm",
      reason: "DASH manifest declares ContentProtection"
    });
  });

  it("has nothing to check for a direct file", () => {
    expect(detectManifestDrm("anything", "direct")).toEqual({ drm_detected: false });
  });
});

describe("isLicenseTraffic", () => {
  it("recognizes common DRM license endpoints", () => {
    expect(isLicenseTraffic("https://cdn.example/widevine/license")).toBe(true);
    expect(isLicenseTraffic("https://drm.example/getlicense?id=1")).toBe(true);
    expect(isLicenseTraffic("https://cdn.example/fairplay/acquireLicense")).toBe(true);
  });

  it("leaves ordinary media and manifest requests alone", () => {
    expect(isLicenseTraffic("https://cdn.example/master.m3u8")).toBe(false);
    expect(isLicenseTraffic("https://cdn.example/segment-1.ts")).toBe(false);
  });
});

describe("mergeDiscoveryResults", () => {
  const topFrame: DiscoveryResult = {
    page_url: "https://app.example/watch/1",
    page_title: "Example",
    preferred_language: "en",
    drm_detected: false,
    media_candidates: [],
    caption_candidates: []
  };

  it("returns undefined when no frame produced a result", () => {
    expect(mergeDiscoveryResults([{ frameId: 0 }, { frameId: 12 }])).toBeUndefined();
  });

  it("takes the page identity from the top frame, wherever it sits in the array", () => {
    const iframe: DiscoveryResult = {
      page_url: "https://player.example/embed/1",
      page_title: "Embedded player",
      drm_detected: false,
      media_candidates: [],
      caption_candidates: []
    };
    const merged = mergeDiscoveryResults([
      { frameId: 7, result: iframe },
      { frameId: 0, result: topFrame }
    ]);
    expect(merged?.page_url).toBe(topFrame.page_url);
    expect(merged?.page_title).toBe(topFrame.page_title);
    expect(merged?.preferred_language).toBe("en");
  });

  it("falls back to the first frame with a result if frameId 0 never produced one", () => {
    const iframe: DiscoveryResult = { ...topFrame, page_url: "https://player.example/embed/1" };
    const merged = mergeDiscoveryResults([{ frameId: 3, result: iframe }, { frameId: 9 }]);
    expect(merged?.page_url).toBe(iframe.page_url);
  });

  it("merges and dedups media and caption candidates found in an iframe", () => {
    const embeddedVideo: DiscoveryResult = {
      ...topFrame,
      page_url: "https://player.example/embed/1",
      media_candidates: [
        { kind: "direct", url: "https://cdn.example/clip.mp4", mime_type: "video/mp4", source: "video" }
      ],
      caption_candidates: [
        { url: "https://cdn.example/en.vtt", format: "vtt", is_active: true, is_manual: true, is_visible_transcript: false }
      ]
    };
    const merged = mergeDiscoveryResults([
      { frameId: 0, result: topFrame },
      { frameId: 4, result: embeddedVideo },
      // The same clip fetched twice (e.g. by a nested iframe) must not appear twice.
      { frameId: 5, result: embeddedVideo }
    ]);
    expect(merged?.media_candidates).toHaveLength(1);
    expect(merged?.media_candidates[0]?.url).toBe("https://cdn.example/clip.mp4");
    expect(merged?.caption_candidates).toHaveLength(1);
  });

  it("treats the page as DRM-protected if any frame reports it", () => {
    const protectedFrame: DiscoveryResult = { ...topFrame, page_url: "https://player.example/embed/1", drm_detected: true };
    const merged = mergeDiscoveryResults([
      { frameId: 0, result: topFrame },
      { frameId: 4, result: protectedFrame }
    ]);
    expect(merged?.drm_detected).toBe(true);
  });

  it("caps the merged totals at 100 media and 50 caption candidates", () => {
    const many = (count: number, make: (index: number) => DiscoveryResult["media_candidates"][number]) =>
      Array.from({ length: count }, (_, index) => make(index));
    const frameA: DiscoveryResult = {
      ...topFrame,
      media_candidates: many(80, (index) => ({
        kind: "direct",
        url: `https://cdn.example/a-${index}.mp4`,
        mime_type: "",
        source: "video"
      }))
    };
    const frameB: DiscoveryResult = {
      ...topFrame,
      page_url: "https://player.example/embed/1",
      media_candidates: many(80, (index) => ({
        kind: "direct",
        url: `https://cdn.example/b-${index}.mp4`,
        mime_type: "",
        source: "video"
      }))
    };
    const merged = mergeDiscoveryResults([
      { frameId: 0, result: frameA },
      { frameId: 1, result: frameB }
    ]);
    expect(merged?.media_candidates).toHaveLength(100);
  });
});

