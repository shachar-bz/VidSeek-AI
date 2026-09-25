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
  /** A media playlist's segments, each placed on the video's timeline. */
  segments: PlaylistSegment[];
  /** A media playlist of subtitle cues, not audio or video. */
  subtitlesOnly: boolean;
}

export interface PlaylistSegment {
  url: string;
  startSeconds: number;
  endSeconds: number;
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
    return {
      role: "master",
      renditionUrls,
      maxHeight,
      segments: [],
      subtitlesOnly: false,
    };
  }

  let durationSeconds = 0;
  let pendingLength = 0;
  const segments: PlaylistSegment[] = [];
  for (const line of lines) {
    if (!line) continue;
    const length = /^#EXTINF:([\d.]+)/i.exec(line)?.[1];
    if (length) {
      pendingLength = Number(length) || 0;
      continue;
    }
    if (line.startsWith("#")) continue;
    const url = resolve(line);
    if (url)
      segments.push({
        url,
        startSeconds: durationSeconds,
        endSeconds: durationSeconds + pendingLength,
      });
    durationSeconds += pendingLength;
    pendingLength = 0;
  }
  return {
    role: "media",
    renditionUrls: [],
    durationSeconds: durationSeconds || undefined,
    segments,
    subtitlesOnly:
      segments.length > 0 &&
      segments.every((segment) => SUBTITLE_SEGMENT.test(segment.url)),
  };
}

/**
 * How much of a video the player actually fetched while the capture ran, on the video's
 * own timeline. Renditions of one video share that timeline, so a player that switched
 * quality halfway, or fetched audio alongside video, still counts each moment once.
 */
function playedSeconds(
  playlists: HlsPlaylistSummary[],
  requestedKeys: Set<string>,
): number {
  const intervals = playlists
    .flatMap((playlist) => playlist.segments)
    .filter((segment) => requestedKeys.has(playlistKey(segment.url)))
    .map((segment): [number, number] => [segment.startSeconds, segment.endSeconds])
    .sort((left, right) => left[0] - right[0]);
  let total = 0;
  let coveredUntil = -Infinity;
  for (const [start, end] of intervals) {
    if (end <= coveredUntil) continue;
    total += end - Math.max(start, coveredUntil);
    coveredUntil = end;
  }
  return total;
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
 * Each also says how much of it was played during the capture, read from which of its
 * segments were among `requestedUrls`: the video the user watched is the one that played.
 *
 * `playlistBodies` maps a playlist URL to its text. A playlist whose body the debugger had
 * already evicted cannot be read, and is kept as it is.
 */
export function collapseHlsRenditions(
  candidates: MediaCandidate[],
  playlistBodies: Map<string, string>,
  requestedUrls: Iterable<string> = [],
): MediaCandidate[] {
  const requestedKeys = new Set([...requestedUrls].map(playlistKey));
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
      return [
        {
          ...candidate,
          duration_seconds: summary.durationSeconds,
          played_seconds: playedSeconds([summary], requestedKeys),
        },
      ];
    }
    // A master has no length of its own; any one of its captured renditions has the video's.
    const renditions = summary.renditionUrls.flatMap((rendition) => {
      const media = mediaByKey.get(playlistKey(rendition));
      return media ? [media] : [];
    });
    return [
      {
        ...candidate,
        duration_seconds: renditions.find((media) => media.durationSeconds)
          ?.durationSeconds,
        max_height: summary.maxHeight,
        played_seconds: playedSeconds(renditions, requestedKeys),
      },
    ];
  });
}
