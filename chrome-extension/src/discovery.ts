import type { DiscoveryResult, MediaCandidate, MediaKind } from "./types";

const MEDIA_EXTENSIONS = /\.(mp4|m4v|mov|webm|mkv|avi)(?:$|[?#])/i;
const HLS = /\.m3u8(?:$|[?#])/i;
const DASH = /\.mpd(?:$|[?#])/i;

export function classifyMediaUrl(url: string, mimeType = ""): MediaKind | null {
  const mime = mimeType.toLowerCase();
  if (HLS.test(url) || mime.includes("mpegurl")) return "hls";
  if (DASH.test(url) || mime.includes("dash+xml")) return "dash";
  if (MEDIA_EXTENSIONS.test(url) || mime.startsWith("video/")) return "direct";
  return null;
}

export function originPatterns(discovery: DiscoveryResult): string[] {
  const urls = [
    discovery.page_url,
    ...discovery.media_candidates.map((item) => item.url),
    ...discovery.caption_candidates.flatMap((item) => (item.url ? [item.url] : []))
  ];
  const patterns = new Set<string>();
  for (const value of urls) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        // Match patterns have no port component; including one is rejected outright.
        patterns.add(`${parsed.protocol}//${parsed.hostname}/*`);
      }
    } catch {
      // DOMs occasionally contain relative or malformed metadata URLs.
    }
  }
  return [...patterns];
}

export function chooseDirectCandidate(candidates: MediaCandidate[]): MediaCandidate | undefined {
  return candidates.find((candidate) => candidate.kind === "direct");
}

/** One entry per frame `discoverPage` ran in, as `chrome.scripting.executeScript` returns them. */
export interface FrameDiscoveryResult {
  frameId: number;
  result?: DiscoveryResult;
}

const MAX_MEDIA_CANDIDATES = 100;
const MAX_CAPTION_CANDIDATES = 50;

/**
 * Combines one `DiscoveryResult` per frame into one page-wide result.
 *
 * An embedded player (Vimeo, JW Player, Brightcove, Kaltura) usually lives in an iframe, so
 * `discoverPage` has to run in every frame, not just the top one, to see it. The top frame
 * (frameId 0) still owns the identity of the page -- its URL, title and language -- but a
 * DRM flag or a media/caption candidate from any frame counts.
 */
export function mergeDiscoveryResults(frames: FrameDiscoveryResult[]): DiscoveryResult | undefined {
  const withResult = frames.filter(
    (frame): frame is FrameDiscoveryResult & { result: DiscoveryResult } => Boolean(frame.result)
  );
  const first = withResult[0];
  if (!first) return undefined;
  const top = withResult.find((frame) => frame.frameId === 0) ?? first;

  const media = new Map<string, MediaCandidate>();
  const captions = new Map<string, DiscoveryResult["caption_candidates"][number]>();
  let drmDetected = false;
  let visibleTranscriptIndex = 0;

  for (const frame of withResult) {
    drmDetected = drmDetected || frame.result.drm_detected;
    for (const candidate of frame.result.media_candidates) {
      if (!media.has(candidate.url)) media.set(candidate.url, candidate);
    }
    for (const caption of frame.result.caption_candidates) {
      const key = caption.url ?? `visible:${visibleTranscriptIndex++}`;
      if (!captions.has(key)) captions.set(key, caption);
    }
  }

  return {
    page_url: top.result.page_url,
    page_title: top.result.page_title,
    preferred_language: top.result.preferred_language,
    drm_detected: drmDetected,
    media_candidates: [...media.values()].slice(0, MAX_MEDIA_CANDIDATES),
    caption_candidates: [...captions.values()].slice(0, MAX_CAPTION_CANDIDATES)
  };
}

export function discoverPage(): DiscoveryResult {
  const mediaExtensions = /\.(mp4|m4v|mov|webm|mkv|avi)(?:$|[?#])/i;
  const hls = /\.m3u8(?:$|[?#])/i;
  const dash = /\.mpd(?:$|[?#])/i;
  const caption = /\.(vtt|srt|ttml)(?:$|[?#])/i;
  const absolute = (value: string): string => {
    try {
      return new URL(value, document.baseURI).href;
    } catch {
      return value;
    }
  };
  const classify = (url: string, mime = ""): MediaKind | null => {
    const lowered = mime.toLowerCase();
    if (hls.test(url) || lowered.includes("mpegurl")) return "hls";
    if (dash.test(url) || lowered.includes("dash+xml")) return "dash";
    if (mediaExtensions.test(url) || lowered.startsWith("video/")) return "direct";
    return null;
  };
  const media = new Map<string, MediaCandidate>();
  const captions = new Map<string, DiscoveryResult["caption_candidates"][number]>();
  const addMedia = (url: string, mime: string, source: string): void => {
    if (!url || url.startsWith("blob:") || url.startsWith("data:")) return;
    const resolved = absolute(url);
    const kind = classify(resolved, mime);
    if (kind && !media.has(resolved)) {
      media.set(resolved, { kind, url: resolved, mime_type: mime, source });
    }
  };

  const videos = [...document.querySelectorAll("video")];
  for (const video of videos) {
    addMedia(video.currentSrc || video.src, video.getAttribute("type") || "", "video");
    for (const source of video.querySelectorAll("source")) {
      addMedia(source.src, source.type, "source");
    }
    for (const track of video.querySelectorAll("track")) {
      if (!track.src) continue;
      captions.set(absolute(track.src), {
        url: absolute(track.src),
        format: track.src.split(/[?#]/)[0]?.split(".").pop()?.toLowerCase() || "vtt",
        language: track.srclang || undefined,
        is_active: track.track.mode === "showing",
        is_manual: !/auto/i.test(track.label),
        is_visible_transcript: false
      });
    }
  }

  for (const selector of [
    'meta[property="og:video"]',
    'meta[property="og:video:url"]',
    'meta[property="og:video:secure_url"]'
  ]) {
    const node = document.querySelector<HTMLMetaElement>(selector);
    if (node?.content) addMedia(node.content, "", "metadata");
  }

  for (const script of document.querySelectorAll<HTMLScriptElement>('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(script.textContent || "null");
      const queue = Array.isArray(parsed) ? [...parsed] : [parsed];
      while (queue.length) {
        const value = queue.shift();
        if (!value || typeof value !== "object") continue;
        if (typeof value.contentUrl === "string") addMedia(value.contentUrl, "", "json-ld");
        if (Array.isArray(value["@graph"])) queue.push(...value["@graph"]);
      }
    } catch {
      // Ignore invalid JSON-LD blocks.
    }
  }

  for (const entry of performance.getEntriesByType("resource") as PerformanceResourceTiming[]) {
    if (caption.test(entry.name)) {
      captions.set(entry.name, {
        url: entry.name,
        format: entry.name.split(/[?#]/)[0]?.split(".").pop()?.toLowerCase() || "vtt",
        is_active: false,
        is_manual: true,
        is_visible_transcript: false
      });
    } else {
      addMedia(entry.name, "", `performance:${entry.initiatorType}`);
    }
  }

  const transcriptSelectors = [
    '[id*="transcript" i]',
    '[class*="transcript" i]',
    '[aria-label*="transcript" i]',
    '[data-testid*="transcript" i]'
  ];
  for (const element of document.querySelectorAll<HTMLElement>(transcriptSelectors.join(","))) {
    const text = element.innerText.split(/\s+/).join(" ").trim();
    if (text.length >= 80 && text.length <= 200_000) {
      captions.set(`visible:${captions.size}`, {
        text,
        format: "text",
        language: document.documentElement.lang || undefined,
        is_active: false,
        is_manual: true,
        is_visible_transcript: true
      });
      break;
    }
  }

  return {
    page_url: location.href,
    page_title: document.title || "video",
    preferred_language: document.documentElement.lang || undefined,
    drm_detected: videos.some((video) => video.mediaKeys !== null),
    media_candidates: [...media.values()].slice(0, 100),
    caption_candidates: [...captions.values()].slice(0, 50)
  };
}
