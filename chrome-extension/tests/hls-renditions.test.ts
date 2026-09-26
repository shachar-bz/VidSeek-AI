// Fold a captured HLS video's renditions into its master, and name what is left for the picker.
import { describe, expect, it } from "vitest";

import { describeCapturedSources } from "../src/discovery";
import { collapseHlsRenditions, summarizeHlsPlaylist } from "../src/hls-renditions";
import type { MediaCandidate } from "../src/types";

const BASE = "https://hls.example/project_masters/10856";
const MASTER_URL = `${BASE}/manifest.m3u8?intro_master_id=7275&preview`;

// Shaped like a TED talk's master: video renditions on their own lines, audio and
// subtitles in URI attributes, one of them root-relative.
const MASTER = `#EXTM3U
#EXT-X-VERSION:4
#EXT-X-STREAM-INF:BANDWIDTH=1095111,RESOLUTION=854x480,AUDIO="audio0",SUBTITLES="subs"
index-f9-v1.m3u8?intro_master_id=7275&preview=true
#EXT-X-STREAM-INF:BANDWIDTH=148959,RESOLUTION=320x180,AUDIO="audio0",SUBTITLES="subs"
index-f1-v1.m3u8?intro_master_id=7275&preview=true
#EXT-X-STREAM-INF:BANDWIDTH=4120461,RESOLUTION=1920x1080,AUDIO="audio0",SUBTITLES="subs"
index-f14-v1.m3u8?intro_master_id=7275&preview=true
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=4504,RESOLUTION=320x180,URI="iframes-f1-v1.m3u8?preview=true"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio0",NAME="medium",URI="index-f8-a1.m3u8?intro_master_id=7275&preview=true"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="en",URI="/project_masters/10856/subtitles/en.m3u8?preview=true"
`;

function mediaPlaylist(segmentSeconds: number[], extension = "ts"): string {
  return [
    "#EXTM3U",
    "#EXT-X-TARGETDURATION:6",
    ...segmentSeconds.flatMap((seconds, index) => [
      `#EXTINF:${seconds.toFixed(4)},`,
      `https://cdn.example/segment-${index}.${extension}`,
    ]),
    "#EXT-X-ENDLIST",
  ].join("\n");
}

const TALK = mediaPlaylist([6, 1.8, ...Array<number>(100).fill(6)]);

function hls(url: string): MediaCandidate {
  return { kind: "hls", url, mime_type: "", source: "debugger" };
}

describe("summarizeHlsPlaylist", () => {
  it("lists every rendition a master points to, resolved against the master", () => {
    const summary = summarizeHlsPlaylist(MASTER, MASTER_URL);
    expect(summary.role).toBe("master");
    expect(summary.maxHeight).toBe(1080);
    expect(summary.renditionUrls).toEqual([
      `${BASE}/index-f9-v1.m3u8?intro_master_id=7275&preview=true`,
      `${BASE}/index-f1-v1.m3u8?intro_master_id=7275&preview=true`,
      `${BASE}/index-f14-v1.m3u8?intro_master_id=7275&preview=true`,
      `${BASE}/iframes-f1-v1.m3u8?preview=true`,
      `${BASE}/index-f8-a1.m3u8?intro_master_id=7275&preview=true`,
      `https://hls.example/project_masters/10856/subtitles/en.m3u8?preview=true`,
    ]);
  });

  it("adds up a media playlist's segments and spots one that is only subtitles", () => {
    expect(summarizeHlsPlaylist(TALK, `${BASE}/index-f1-v1.m3u8`)).toMatchObject({
      role: "media",
      durationSeconds: 607.8,
      subtitlesOnly: false,
    });
    expect(
      summarizeHlsPlaylist(mediaPlaylist([60, 60], "vtt"), `${BASE}/en.m3u8`)
        .subtitlesOnly,
    ).toBe(true);
  });
});

describe("collapseHlsRenditions", () => {
  it("includes the page title when naming captured sources", () => {
    expect(describeCapturedSources([hls(MASTER_URL)], "Sam Altman at TED2025")[0]!.label)
      .toBe("Sam Altman at TED2025 · Source 1 · length unknown");
  });
  it("folds TED audio and quality variants even when their response bodies are unavailable", () => {
    const variants = ["index-f1-v1", "index-f8-a1", "index-f9-v1"]
      .map(name => hls(`${BASE}/${name}.m3u8?intro_master_id=7275&preview=true`));
    const collapsed = collapseHlsRenditions(
      [hls(MASTER_URL), ...variants], new Map([[MASTER_URL, MASTER]]),
    );
    expect(collapsed.map(c => c.url)).toEqual([MASTER_URL]);
  });
  it("turns a master and the renditions the player fetched into one video", () => {
    const renditions = [
      `${BASE}/index-f1-v1.m3u8?intro_master_id=7275&preview=true`,
      `${BASE}/index-f8-a1.m3u8?intro_master_id=7275&preview=true`,
      `${BASE}/index-f9-v1.m3u8?intro_master_id=7275&preview=true`,
      // The player's own cache-buster: still the rendition the master names.
      `${BASE}/index-f14-v1.m3u8?intro_master_id=7275&preview=true&_=123`,
    ];
    const bodies = new Map<string, string>([
      [MASTER_URL, MASTER],
      ...renditions.map((url): [string, string] => [url, TALK]),
    ]);
    const collapsed = collapseHlsRenditions(
      [hls(MASTER_URL), ...renditions.map(hls)],
      bodies,
    );
    expect(collapsed).toEqual([
      {
        ...hls(MASTER_URL),
        duration_seconds: 607.8,
        max_height: 1080,
        played_seconds: 0,
      },
    ]);
  });

  it("keeps two unrelated videos apart, and drops a stray subtitles playlist", () => {
    const talk = `${BASE}/talk.m3u8`;
    const ad = "https://ads.example/sponsor.m3u8";
    const subtitles = "https://hls.example/other/en.m3u8";
    const collapsed = collapseHlsRenditions(
      [hls(talk), hls(ad), hls(subtitles)],
      new Map([
        [talk, TALK],
        [ad, mediaPlaylist([6, 6, 3])],
        [subtitles, mediaPlaylist([60], "vtt")],
      ]),
    );
    expect(collapsed.map((c) => [c.url, c.duration_seconds])).toEqual([
      [talk, 607.8],
      [ad, 15],
    ]);
  });

  it("keeps a playlist whose body the debugger no longer had, as it was", () => {
    const candidates = [hls(MASTER_URL), hls(`${BASE}/index-f1-v1.m3u8`)];
    expect(collapseHlsRenditions(candidates, new Map())).toEqual(candidates);
  });
});

describe("played during the capture", () => {
  it("counts each moment once across renditions, and nothing for a video left unplayed", () => {
    const low = `${BASE}/index-f1-v1.m3u8?intro_master_id=7275&preview=true`;
    const high = `${BASE}/index-f14-v1.m3u8?intro_master_id=7275&preview=true`;
    const ad = "https://ads.example/sponsor.m3u8";
    const segments = (quality: string, count: number): string[] =>
      Array.from({ length: count }, (_, i) => `https://cdn.example/${quality}/s${i}.ts`);
    const playlist = (quality: string): string =>
      [
        "#EXTM3U",
        ...segments(quality, 10).flatMap((url) => ["#EXTINF:6.0,", url]),
      ].join("\n");
    const collapsed = collapseHlsRenditions(
      [hls(MASTER_URL), hls(low), hls(high), hls(ad)],
      new Map([
        [MASTER_URL, MASTER],
        [low, playlist("low")],
        [high, playlist("high")],
        [ad, mediaPlaylist([6, 6, 3])],
      ]),
      // The player started low, switched up after 12 seconds, and fetched both for one
      // stretch in between: 0-12s low, 6-30s high, so 30 seconds were played.
      [...segments("low", 2), ...segments("high", 5).slice(1)],
    );
    expect(collapsed.map((c) => [c.url, c.played_seconds])).toEqual([
      [MASTER_URL, 30],
      [ad, 0],
    ]);
  });
});

describe("describeCapturedSources", () => {
  it("puts the longest first, says which one was played, and calls out a likely ad", () => {
    const choices = describeCapturedSources([
      { ...hls("https://ads.example/sponsor.m3u8"), duration_seconds: 15, played_seconds: 0 },
      { ...hls(MASTER_URL), duration_seconds: 607.8, max_height: 1080, played_seconds: 42 },
    ]);
    expect(choices.map(({ label, detail, recommended }) => [label, detail, recommended])).toEqual([
      [
        "Video 1 · 10:08 · up to 1080p",
        "You played 0:42 of it, longest, most likely the main video",
        true,
      ],
      [
        "Video 2 · 0:15",
        "Not played during the check, short, probably an ad or intro",
        false,
      ],
    ]);
  });

  it("recommends the one that was played when no length is known", () => {
    const choices = describeCapturedSources([
      hls("https://a.example/one.m3u8"),
      { ...hls("https://b.example/two.m3u8"), played_seconds: 20 },
    ]);
    expect(choices.map(({ label, detail, recommended }) => [label, detail, recommended])).toEqual([
      ["Video 1 · length unknown", "Not played during the check", false],
      ["Video 2 · length unknown", "You played 0:20 of it", true],
    ]);
  });

  it("falls back to where each one streams from when nothing else is known", () => {
    const choices = describeCapturedSources([
      hls("https://a.example/one.m3u8"),
      hls("https://b.example/two.m3u8"),
    ]);
    expect(choices.map(({ detail, recommended }) => [detail, recommended])).toEqual([
      ["Streamed from a.example", false],
      ["Streamed from b.example", false],
    ]);
  });
});
