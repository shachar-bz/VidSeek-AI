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

/** Mirrors the companion's is_youtube_url, which also covers m./music. subdomains. */
export function isYouTubeUrl(url: string): boolean {
  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return false;
  }
  return (
    hostname === "youtu.be" ||
    hostname === "youtube.com" ||
    hostname.endsWith(".youtube.com") ||
    hostname === "youtube-nocookie.com" ||
    hostname.endsWith(".youtube-nocookie.com")
  );
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
 *
 * A frame that is itself hosted on YouTube (an embedded player on an otherwise unrelated
 * page, e.g. an edX Video XBlock configured with a YouTube ID) is the one exception: its
 * `discoverPage` result already stands in for the whole page -- see the YouTube branch of
 * `discoverPage` below -- and takes over the merge outright, the same way `popup.ts` skips
 * discovery entirely when the tab itself is a YouTube page. Mixing it with candidates found
 * in sibling frames would only produce expiring googlevideo links.
 */
export function mergeDiscoveryResults(frames: FrameDiscoveryResult[]): DiscoveryResult | undefined {
  const withResult = frames.filter(
    (frame): frame is FrameDiscoveryResult & { result: DiscoveryResult } => Boolean(frame.result)
  );
  const first = withResult[0];
  if (!first) return undefined;
  const youtubeFrame = withResult.find((frame) => isYouTubeUrl(frame.result.page_url));
  if (youtubeFrame) return youtubeFrame.result;
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

/** One frame's worth of candidates, offered to the user as a single choice of video. */
export interface VideoGroup {
  frameId: number;
  label: string;
  result: DiscoveryResult;
}

function isEmptyFrameResult(result: DiscoveryResult): boolean {
  return (
    !isYouTubeUrl(result.page_url) &&
    result.media_candidates.length === 0 &&
    result.caption_candidates.length === 0
  );
}

function describeVideoGroup(result: DiscoveryResult, frameId: number, topPageTitle: string): string {
  if (isYouTubeUrl(result.page_url)) return `YouTube: ${result.page_title.replace(/ - YouTube$/, "")}`;
  if (result.page_title && result.page_title !== topPageTitle) return result.page_title;
  const mediaCount = `${result.media_candidates.length} media source(s)`;
  return frameId === 0 ? `Main page (${mediaCount})` : `Embedded player (${mediaCount})`;
}

/**
 * Splits per-frame discovery results into the distinct videos found on the page, when there
 * is more than one to choose from.
 *
 * A frame with no media candidates, no caption candidates, and no YouTube identity found
 * nothing and is not offered as a choice -- most frames on a typical page (ads, widgets,
 * analytics iframes) fall here. Returns undefined when zero or one frame found anything, so
 * the caller can fall back to treating the page as having a single video, via
 * `mergeDiscoveryResults`, exactly as before this function existed.
 */
export function findVideoGroups(frames: FrameDiscoveryResult[], topPageTitle: string): VideoGroup[] | undefined {
  const groups = frames
    .filter((frame): frame is FrameDiscoveryResult & { result: DiscoveryResult } => Boolean(frame.result))
    .filter((frame) => !isEmptyFrameResult(frame.result))
    .map((frame) => ({
      frameId: frame.frameId,
      label: describeVideoGroup(frame.result, frame.frameId, topPageTitle),
      result: frame.result
    }));
  return groups.length > 1 ? groups : undefined;
}

/**
 * Turns the user's chosen `VideoGroup` into the `DiscoveryResult` to submit as the job.
 *
 * The chosen frame's own media and caption candidates are used as-is, but -- unless the
 * choice is a YouTube identity, which stands for the whole job on its own -- the page
 * identity (URL, title, language) still comes from the top frame, for the same reason
 * `mergeDiscoveryResults` does that: cookies and the Referer/Origin headers sent to the CDN
 * need to reflect the page the browser was actually on, not an embed's own iframe URL.
 *
 * DRM is scoped to just the chosen frame here, unlike `mergeDiscoveryResults`'s page-wide OR:
 * once the user has picked a specific video, an unrelated frame (an ad, a tracker) reporting
 * DRM must not block a clean choice -- that would defeat the point of letting them choose.
 */
export function resolveSelectedGroup(group: VideoGroup, frames: FrameDiscoveryResult[]): DiscoveryResult {
  if (isYouTubeUrl(group.result.page_url)) return group.result;
  const top = frames.find((frame) => frame.frameId === 0)?.result;
  if (!top) return group.result;
  return {
    page_url: top.page_url,
    page_title: top.page_title,
    preferred_language: top.preferred_language,
    drm_detected: group.result.drm_detected,
    media_candidates: group.result.media_candidates,
    caption_candidates: group.result.caption_candidates
  };
}

export function discoverPage(): DiscoveryResult {
  // A YouTube-hosted frame -- typically an <iframe src="https://www.youtube.com/embed/...">
  // embedded in an otherwise unrelated page -- can never yield a usable media candidate: its
  // <video> element streams through MediaSource (a blob: src, filtered out below) and its
  // actual segments come from expiring, unclassifiable googlevideo.com URLs. Reporting the
  // frame as its own canonical watch page instead lets `mergeDiscoveryResults` route the
  // whole job to the YouTube pipeline, the same one used when the active tab is YouTube
  // itself. This is inlined, rather than calling `isYouTubeUrl`, because this function is
  // injected into the page via `chrome.scripting.executeScript` and runs with no closure
  // over this module's other bindings.
  const youtubeVideoId = ((): string | null => {
    let hostname: string;
    try {
      hostname = location.hostname.toLowerCase().replace(/^www\./, "");
    } catch {
      return null;
    }
    const onYouTube =
      hostname === "youtu.be" ||
      hostname === "youtube.com" ||
      hostname.endsWith(".youtube.com") ||
      hostname === "youtube-nocookie.com" ||
      hostname.endsWith(".youtube-nocookie.com");
    if (!onYouTube) return null;
    const embedMatch = location.pathname.match(/^\/embed\/([\w-]{6,})/);
    if (embedMatch?.[1]) return embedMatch[1];
    const watchId = new URLSearchParams(location.search).get("v");
    if (watchId) return watchId;
    if (hostname === "youtu.be") {
      const shortMatch = location.pathname.match(/^\/([\w-]{6,})/);
      if (shortMatch?.[1]) return shortMatch[1];
    }
    return null;
  })();
  if (youtubeVideoId) {
    return {
      page_url: `https://www.youtube.com/watch?v=${youtubeVideoId}`,
      page_title: document.title || "video",
      drm_detected: false,
      media_candidates: [],
      caption_candidates: []
    };
  }

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
