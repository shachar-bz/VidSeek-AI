// Fold the rendition playlists of one captured HLS video into its master playlist.
import type { MediaCandidate } from "./types";

export interface HlsPlaylistSummary {
  /** A master playlist lists renditions; a media playlist lists one rendition's segments. */
  role: "master" | "media";
  /** Every playlist a master points to (video, audio, subtitles), as absolute URLs. */
  renditionUrls: string[];
  /** The tallest video rendition a master offers, in pixels. */
  maxHeight?: number;
  /** A media playlist's total running time. */
  durationSeconds?: number;
  /** A media playlist of subtitle cues, not audio or video. */
  subtitlesOnly: boolean;
}

const SUBTITLE_SEGMENT = /\.(?:vtt|webvtt|srt)(?:[?#]|$)/i;

export function summarizeHlsPlaylist(
  text: string,
  playlistUrl: string,
): HlsPlaylistSummary {
  const lines = text.split(/\r?\n/).map((line) => line.trim());
  const resolve = (reference: string): string | undefined => {
    try {
      return new URL(reference, playlistUrl).href;
    } catch {
      return undefined;
    }
  };

  if (lines.some((line) => line.startsWith("#EXT-X-STREAM-INF"))) {
    const renditionUrls: string[] = [];
    let maxHeight: number | undefined;
    let awaitingStreamUri = false;
    for (const line of lines) {
      if (!line) continue;
      if (line.startsWith("#EXT-X-STREAM-INF")) {
        const height = Number(/RESOLUTION=\d+x(\d+)/i.exec(line)?.[1]);
        if (height) maxHeight = Math.max(maxHeight ?? 0, height);
        awaitingStreamUri = true;
        continue;
      }
      if (line.startsWith("#")) {
        // Audio, subtitle and I-frame renditions name their playlist in a URI attribute.
        const uri = /URI="([^"]+)"/i.exec(line)?.[1];
        const resolved = uri && resolve(uri);
        if (resolved) renditionUrls.push(resolved);
        continue;
      }
      if (awaitingStreamUri) {
        const resolved = resolve(line);
        if (resolved) renditionUrls.push(resolved);
        awaitingStreamUri = false;
      }
    }
    return { role: "master", renditionUrls, maxHeight, subtitlesOnly: false };
  }

  let durationSeconds = 0;
  for (const line of lines) {
    const length = Number(/^#EXTINF:([\d.]+)/i.exec(line)?.[1]);
    if (length) durationSeconds += length;
  }
  const segments = lines.filter((line) => line && !line.startsWith("#"));
  return {
    role: "media",
    renditionUrls: [],
    durationSeconds: durationSeconds || undefined,
    subtitlesOnly:
      segments.length > 0 &&
      segments.every((segment) => SUBTITLE_SEGMENT.test(segment)),
  };
}

/**
 * Players tack their own query strings (session tokens, cache busters) onto rendition URLs,
 * so a master's reference and the request the player actually made are matched without it.
 */
function playlistKey(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.origin + parsed.pathname;
  } catch {
    return url;
  }
}

/**
 * One adaptive video shows up in a capture as several playlists: its master, plus whichever
 * video, audio and subtitle renditions the player went on to fetch. Offering each of those
 * as its own video asks the user to choose between copies of the same thing, so a playlist a
 * captured master points to is folded into that master, and a subtitles-only playlist is
 * dropped. What is left carries its length and resolution, so that when a capture really
 * did see several videos (an ad and the talk, say) the picker can tell them apart.
 *
 * `playlistBodies` maps a playlist URL to its text. A playlist whose body the debugger had
 * already evicted cannot be read, and is kept as it is.
 */
export function collapseHlsRenditions(
  candidates: MediaCandidate[],
  playlistBodies: Map<string, string>,
): MediaCandidate[] {
  const summaries = new Map<string, HlsPlaylistSummary>();
  for (const candidate of candidates) {
    const body = playlistBodies.get(candidate.url);
    if (candidate.kind === "hls" && body)
      summaries.set(candidate.url, summarizeHlsPlaylist(body, candidate.url));
  }
  const mediaByKey = new Map(
    [...summaries]
      .filter(([, summary]) => summary.role === "media")
      .map(([url, summary]) => [playlistKey(url), summary]),
  );
  const ownedByMaster = new Set<string>();
  for (const [url, summary] of summaries) {
    if (summary.role !== "master") continue;
    for (const rendition of summary.renditionUrls) {
      const key = playlistKey(rendition);
      if (key !== playlistKey(url)) ownedByMaster.add(key);
    }
  }

  return candidates.flatMap((candidate) => {
    const summary = summaries.get(candidate.url);
    if (!summary) return [candidate];
    if (summary.role === "media") {
      if (ownedByMaster.has(playlistKey(candidate.url)) || summary.subtitlesOnly)
        return [];
      return [{ ...candidate, duration_seconds: summary.durationSeconds }];
    }
    // A master has no length of its own; any one of its captured renditions has the video's.
    const duration = summary.renditionUrls
      .map((rendition) => mediaByKey.get(playlistKey(rendition)))
      .find((rendition) => rendition?.durationSeconds)?.durationSeconds;
    return [
      {
        ...candidate,
        duration_seconds: duration,
        max_height: summary.maxHeight,
      },
    ];
  });
}
