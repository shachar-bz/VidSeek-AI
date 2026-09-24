// Fold a captured HLS video's renditions into its master, and name what is left for the picker.
import { describe, expect, it } from "vitest";

import { describeCapturedSources, LIKELY_MAIN_VIDEO_DETAIL } from "../src/discovery";
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
      { ...hls(MASTER_URL), duration_seconds: 607.8, max_height: 1080 },
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

describe("describeCapturedSources", () => {
  it("puts the longest first and calls out a short clip as a likely ad", () => {
    const choices = describeCapturedSources([
      { ...hls("https://ads.example/sponsor.m3u8"), duration_seconds: 15 },
      { ...hls(MASTER_URL), duration_seconds: 607.8, max_height: 1080 },
    ]);
    expect(choices.map(({ label, detail }) => [label, detail])).toEqual([
      ["Video 1 · 10:08 · up to 1080p", LIKELY_MAIN_VIDEO_DETAIL],
      ["Video 2 · 0:15", "Short clip, probably an ad or intro"],
    ]);
  });

  it("falls back to where each one streams from when no length is known", () => {
    const choices = describeCapturedSources([
      hls("https://a.example/one.m3u8"),
      hls("https://b.example/two.m3u8"),
    ]);
    expect(choices.map(({ label, detail }) => [label, detail])).toEqual([
      ["Video 1 · length unknown", "Streamed from a.example"],
      ["Video 2 · length unknown", "Streamed from b.example"],
    ]);
  });
});
