// Regression fixtures based on the six inspected sites, without signed URLs or cookies.
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { discoverPage } from "../src/page-discovery";
import { findVideoGroups, mergeDiscoveryResults } from "../src/discovery";

beforeEach(() => {
  document.body.innerHTML = "";
  document.head.innerHTML = "<title>Test page</title>";
  vi.spyOn(performance, "getEntriesByType").mockReturnValue([]);
});
const json = (value: unknown) => {
  const s = document.createElement("script");
  s.type = "application/json";
  s.textContent = JSON.stringify(value);
  document.body.append(s);
};
describe("rendered page discovery", () => {
  it("Coursera: collects signed sources and extensionless subtitle proxies", () => {
    document.body.innerHTML =
      '<video><source src="https://cdn.example/course.webm?sig=one" type="video/webm"><track kind="captions" srclang="en" src="https://www.coursera.org/api/subtitleAssetProxy.v1/a?fileExtension=vtt"></video>';
    const g = discoverPage().videos![0]!;
    expect(g.media_candidates[0]!.url).toContain("sig=one");
    expect(g.caption_candidates[0]).toMatchObject({
      format: "vtt",
      language: "en",
    });
  });
  it("TED: ignores the ad and resolves the blob through hydration data", () => {
    document.body.innerHTML =
      '<video title="Advertisement" src="https://gcdn.2mdn.net/ad.mp4"></video><video id="video" src="blob:https://ted.com/id"></video>';
    json({
      props: {
        pageProps: { videoData: { hlsUrl: "https://hls.ted.com/master.m3u8" } },
      },
    });
    const groups = discoverPage().videos!;
    expect(groups).toHaveLength(1);
    expect(groups[0]!.media_candidates.map((c) => c.url)).toEqual([
      "https://hls.ted.com/master.m3u8",
    ]);
    expect(groups[0]!.drm_detected).toBe(false);
  });
  it("ynet: separates three videos configured in inline scripts before playback", () => {
    for (let i = 0; i < 3; i++) {
      const s = document.createElement("script");
      s.type = "application/fixture";
      s.textContent = `window.YITSiteWidgets.push(['block','SiteVideoMedia',${JSON.stringify({ data: { mediaType: "MEDIA_VIDEO", mediaId: i + 1, title: "Clip " + i, url: `https://vod.example/${i}/manifest.mpd`, downGradeUrl: `https://vod.example/${i}.mp4`, is_drm: false } })}]);`;
      document.body.append(s);
    }
    const groups = findVideoGroups(
      [{ frameId: 0, result: discoverPage() }],
      "Test page",
    )!;
    expect(groups).toHaveLength(3);
    expect(new Set(groups.map((g) => g.result.selected_media_id)).size).toBe(3);
    expect(groups.every((g) => g.result.media_candidates.length === 2)).toBe(
      true,
    );
  });
  it("TikTok: keeps extensionless URLs and separates feed items", () => {
    json({
      __DEFAULT_SCOPE__: {
        "webapp.updated-items": {
          items: [1, 2].map((id) => ({
            id: String(id),
            desc: "clip",
            video: {
              format: "mp4",
              playAddr: `https://cdn.example/play/${id}?signature=secret`,
              downloadAddr: `https://cdn.example/download/${id}`,
            },
          })),
        },
      },
    });
    expect(
      discoverPage().videos!.map((g) => [
        g.selected_media_id,
        g.media_candidates.length,
      ]),
    ).toEqual([
      ["1", 2],
      ["2", 2],
    ]);
  });
  it("Campus: associates Hebrew timed text with its YouTube embed", () => {
    document.body.innerHTML =
      '<div id="video_block"><iframe src="https://www.youtube.com/embed/yiioO9wYbTs"></iframe><span data-start="10440">שלום עולם</span></div>';
    document.querySelector("div")!.setAttribute(
      "data-metadata",
      JSON.stringify({
        transcriptLanguage: "he",
        transcriptTranslationUrl: "/transcript/translation/__lang__",
      }),
    );
    const g = discoverPage().videos![0]!;
    expect(g.page_url).toBe("https://www.youtube.com/watch?v=yiioO9wYbTs");
    expect(g.caption_candidates.find((c) => c.text)?.text).toContain("10.44");
    expect(g.caption_candidates.find((c) => c.url)?.url).toContain(
      "/translation/he",
    );
    expect(
      mergeDiscoveryResults([
        { frameId: 0, result: discoverPage() },
        { frameId: 1, result: { ...g, caption_candidates: [] } },
      ])!.caption_candidates,
    ).toHaveLength(2);
  });
  it("TED Ed: detects a lazy YouTube iframe and rescans newly inserted native players", () => {
    document.body.innerHTML =
      '<iframe data-src="https://www.youtube.com/embed/DCIL2nvU4x8"></iframe>';
    expect(discoverPage().videos![0]!.page_url).toContain("DCIL2nvU4x8");
    document.body.innerHTML =
      '<video><source src="https://cdn.example/stream" type="video/mp4"></video>';
    expect(discoverPage().videos![0]!.media_candidates[0]!.kind).toBe("direct");
  });
  it("keeps unknown numeric/text caption tables for validated field mapping", () => {
    json({
      video: {
        format: "mp4",
        playAddr: "https://cdn.example/file",
        transcript_a: [{ words: "hello", offset: 0, finish: 1500 }],
      },
    });
    expect(discoverPage().videos![0]!.caption_candidates[0]!.format).toBe(
      "json",
    );
  });
  it("keeps shadow-root video sources and does not confuse media segments with files", () => {
    const shadow = document.body
      .appendChild(document.createElement("div"))
      .attachShadow({ mode: "open" });
    shadow.innerHTML =
      '<video src="https://cdn.example/segment.ts"></video><video src="https://cdn.example/full.mp4"></video>';
    expect(
      discoverPage().videos![0]!.media_candidates.map((c) => c.url),
    ).toEqual(["https://cdn.example/full.mp4"]);
  });
});

it("cue duration never overwrites video duration", () => {
  json({
    video: {
      format: "mp4",
      playAddr: "https://cdn.example/file",
      duration: 120,
      transcript_a: [{ words: "hello", start: 40, duration: 2 }],
    },
  });
  expect(discoverPage().videos![0]!.media_duration_seconds).toBe(120);
});

it("resource identity preserves video query parameters but ignores expiring signatures", () => {
  document.body.innerHTML =
    '<video src="https://cdn.example/play.mp4?id=one&amp;sig=a"></video><video src="https://cdn.example/play.mp4?id=two&amp;sig=a"></video>';
  const first = discoverPage().videos!;
  expect(first[0]!.selected_media_id).not.toBe(first[1]!.selected_media_id);
  document.querySelector("video")!.src =
    "https://cdn.example/play.mp4?id=one&sig=b";
  expect(discoverPage().videos![0]!.selected_media_id).toBe(
    first[0]!.selected_media_id,
  );
});

describe("a native <video> source's MIME type", () => {
  const signed = "https://cdn.example/stream?token=abc";
  const servedAs = (contentType: string): void => {
    vi.spyOn(performance, "getEntriesByName").mockReturnValue([
      { contentType } as unknown as PerformanceEntry,
    ]);
  };

  it("takes each URL's type from the <source> that names it", () => {
    const webm = "https://cdn.example/course.webm?sig=one";
    document.body.innerHTML = `<video><source src="${webm}" type="video/webm"></video>`;
    expect(discoverPage().videos![0]!.media_candidates).toEqual([
      expect.objectContaining({ url: webm, kind: "direct", mime_type: "video/webm" }),
    ]);
  });

  it("keeps an extensionless <video src> the browser reports was served as video", () => {
    document.body.innerHTML = `<video src="${signed}"></video>`;
    servedAs("video/mp4");
    expect(discoverPage().videos![0]!.media_candidates).toEqual([
      expect.objectContaining({ url: signed, kind: "direct", mime_type: "video/mp4" }),
    ]);
  });

  it("classifies an extensionless playlist Chrome plays natively as HLS, not a file", () => {
    document.body.innerHTML = `<video src="${signed}"></video>`;
    servedAs("application/vnd.apple.mpegurl");
    expect(discoverPage().videos![0]!.media_candidates).toEqual([
      expect.objectContaining({ url: signed, kind: "hls" }),
    ]);
  });

  it("leaves an extensionless <video src> with no reported type to the playback check", () => {
    document.body.innerHTML = `<video src="${signed}"></video>`;
    servedAs("");
    expect(discoverPage().videos![0]!.media_candidates).toEqual([]);
  });
});
