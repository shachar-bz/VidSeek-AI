import { describe, expect, it } from "vitest";

import {
  classifyMediaUrl,
  chooseDirectCandidate,
  detectManifestDrm,
  findVideoGroups,
  isLicenseTraffic,
  isYouTubeUrl,
  mergeDiscoveryResults,
  originPatterns,
  pageOriginPatterns,
  resolveSelectedGroup
} from "../src/discovery";
import type { FrameDiscoveryResult } from "../src/discovery";
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

  it("separates the page and its video frame from CDN and caption hosts", () => {
    const discovery: DiscoveryResult = {
      page_url: "https://www.ted.com/talks/1",
      frame_url: "https://player.ted.com/embed/1",
      page_title: "Talk",
      drm_detected: false,
      media_candidates: [
        { kind: "hls", url: "https://hls.ted.com/master.m3u8", mime_type: "", source: "capture" }
      ],
      caption_candidates: [
        { url: "https://captions.example/en.vtt", format: "vtt", is_active: true, is_manual: true, is_visible_transcript: false }
      ]
    };
    expect(pageOriginPatterns(discovery).sort()).toEqual([
      "https://player.ted.com/*",
      "https://www.ted.com/*"
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

  it("recognizes YouTube hosts, including nocookie and subdomains", () => {
    expect(isYouTubeUrl("https://www.youtube.com/watch?v=abc123")).toBe(true);
    expect(isYouTubeUrl("https://youtu.be/abc123")).toBe(true);
    expect(isYouTubeUrl("https://m.youtube.com/watch?v=abc123")).toBe(true);
    expect(isYouTubeUrl("https://www.youtube-nocookie.com/embed/abc123")).toBe(true);
    expect(isYouTubeUrl("https://player.example/embed/1")).toBe(false);
    expect(isYouTubeUrl("not a url")).toBe(false);
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

  it("lets a YouTube-hosted frame take over the whole merge, even mid-array", () => {
    const embeddedYouTube: DiscoveryResult = {
      page_url: "https://www.youtube.com/watch?v=2GEE0kiF6Dk",
      page_title: "video",
      drm_detected: false,
      media_candidates: [],
      caption_candidates: []
    };
    const siblingFrame: DiscoveryResult = {
      ...topFrame,
      media_candidates: [
        { kind: "direct", url: "https://cdn.example/unrelated.mp4", mime_type: "video/mp4", source: "video" }
      ]
    };
    const merged = mergeDiscoveryResults([
      { frameId: 0, result: siblingFrame },
      { frameId: 3, result: embeddedYouTube }
    ]);
    expect(merged?.page_url).toBe(embeddedYouTube.page_url);
    expect(merged?.media_candidates).toEqual([]);
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

describe("findVideoGroups", () => {
  const mainPage: DiscoveryResult = {
    page_url: "https://app.example/watch/1",
    page_title: "App",
    drm_detected: false,
    media_candidates: [
      { kind: "direct", url: "https://cdn.example/native.mp4", mime_type: "video/mp4", source: "video" }
    ],
    caption_candidates: []
  };
  const vimeoEmbed: DiscoveryResult = {
    page_url: "https://player.vimeo.com/video/1",
    page_title: "Vimeo embed",
    drm_detected: false,
    media_candidates: [
      { kind: "direct", url: "https://cdn.example/vimeo.mp4", mime_type: "video/mp4", source: "video" }
    ],
    caption_candidates: []
  };
  const emptyAdFrame: DiscoveryResult = {
    page_url: "https://ads.example/slot",
    page_title: "ads.example",
    drm_detected: false,
    media_candidates: [],
    caption_candidates: []
  };

  it("returns undefined when at most one frame found anything", () => {
    expect(findVideoGroups([{ frameId: 0, result: mainPage }, { frameId: 1, result: emptyAdFrame }], "App")).toBeUndefined();
    expect(findVideoGroups([{ frameId: 1 }, { frameId: 2, result: emptyAdFrame }], "App")).toBeUndefined();
  });

  it("offers one group per frame that found a video, skipping empty frames", () => {
    const groups = findVideoGroups(
      [
        { frameId: 0, result: mainPage },
        { frameId: 7, result: emptyAdFrame },
        { frameId: 9, result: vimeoEmbed }
      ],
      "App"
    );
    expect(groups).toHaveLength(2);
    expect(groups?.map((group) => group.frameId)).toEqual([0, 9]);
    expect(groups?.[1]?.label).toBe("Vimeo embed");
  });

  it("labels a YouTube-hosted frame distinctly, trimming the ' - YouTube' suffix", () => {
    const youtubeEmbed: DiscoveryResult = {
      page_url: "https://www.youtube.com/watch?v=abc123",
      page_title: "How AI helps at work - YouTube",
      drm_detected: false,
      media_candidates: [],
      caption_candidates: []
    };
    const groups = findVideoGroups(
      [
        { frameId: 0, result: mainPage },
        { frameId: 4, result: youtubeEmbed }
      ],
      "App"
    );
    expect(groups?.[1]?.label).toBe("YouTube: How AI helps at work");
  });

  it("retains shared page titles and marks the playing video, its length and location", () => {
    const secondOnPage: DiscoveryResult = {
      ...mainPage,
      media_candidates: [
        { kind: "direct", url: "https://cdn.example/second.mp4", mime_type: "video/mp4", source: "video" }
      ],
      media_duration_seconds: 754,
      media_playing: true
    };
    const untitledEmbed: DiscoveryResult = {
      ...vimeoEmbed,
      frame_url: "https://player.vimeo.com/video/1",
      page_title: "App"
    };
    const groups = findVideoGroups(
      [
        { frameId: 0, result: { ...mainPage, videos: [mainPage, secondOnPage] } },
        { frameId: 9, result: untitledEmbed }
      ],
      "App"
    );
    expect(groups?.map(({ label, detail, recommended }) => [label, detail, recommended])).toEqual([
      ["App (1)", "In the page itself", false],
      ["App (2)", "Playing now · 12:34", true],
      ["App (3)", "Embedded from player.vimeo.com", false]
    ]);
  });

  it("tells apart two videos that carry the same title", () => {
    const groups = findVideoGroups(
      [
        { frameId: 4, result: vimeoEmbed },
        { frameId: 9, result: { ...vimeoEmbed, media_candidates: [] , caption_candidates: [
          { url: "https://captions.example/en.vtt", format: "vtt", is_active: true, is_manual: true, is_visible_transcript: false }
        ] } }
      ],
      "App"
    );
    expect(groups?.map((group) => group.label)).toEqual(["Vimeo embed (1)", "Vimeo embed (2)"]);
  });
});

describe("resolveSelectedGroup", () => {
  const topFrame: DiscoveryResult = {
    page_url: "https://app.example/watch/1",
    page_title: "App",
    preferred_language: "en",
    drm_detected: true,
    media_candidates: [],
    caption_candidates: []
  };
  const frames: FrameDiscoveryResult[] = [
    { frameId: 0, result: topFrame },
    {
      frameId: 5,
      result: {
        page_url: "https://player.vimeo.com/video/1",
        page_title: "Vimeo embed",
        drm_detected: false,
        media_candidates: [
          { kind: "direct", url: "https://cdn.example/vimeo.mp4", mime_type: "video/mp4", source: "video" }
        ],
        caption_candidates: []
      }
    }
  ];

  it("keeps the top frame's identity but the chosen frame's own candidates and DRM flag", () => {
    const group = { frameId: 5, label: "Vimeo embed", result: frames[1]!.result! };
    const resolved = resolveSelectedGroup(group, frames);
    expect(resolved.page_url).toBe(topFrame.page_url);
    expect(resolved.preferred_language).toBe("en");
    expect(resolved.media_candidates).toEqual(group.result.media_candidates);
    // The top frame flags DRM, but the chosen embed does not -- a clean choice must not be
    // blocked by an unrelated frame (e.g. an ad) reporting DRM.
    expect(resolved.drm_detected).toBe(false);
  });

  it("uses the YouTube identity as-is, without borrowing the top frame's URL", () => {
    const youtubeResult: DiscoveryResult = {
      page_url: "https://www.youtube.com/watch?v=abc123",
      page_title: "video",
      drm_detected: false,
      media_candidates: [],
      caption_candidates: []
    };
    const group = { frameId: 8, label: "YouTube: video", result: youtubeResult };
    const resolved = resolveSelectedGroup(group, frames);
    expect(resolved).toBe(youtubeResult);
  });
});

