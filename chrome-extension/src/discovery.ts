// Classify resources and associate frame discoveries with individual videos.
import type { DiscoveryResult, MediaCandidate, MediaKind } from "./types";

const MEDIA_EXTENSIONS = /\.(mp4|m4v|mov|webm|mkv|avi)(?:$|[?#])/i;
const HLS = /\.m3u8(?:$|[?#])/i;
const DASH = /\.mpd(?:$|[?#])/i;

export function classifyMediaUrl(url: string, mimeType = ""): MediaKind | null {
  if (
    !/^https?:\/\//i.test(url) ||
    /(?:imasdk\.googleapis\.com|doubleclick\.net|2mdn\.net|googlesyndication\.com|\/web_video_ads\/|\/vast(?:[/.?]|$))/i.test(
      url,
    )
  )
    return null;
  if (
    /\.(?:ts|m4s|aac)(?:[?#]|$)/i.test(url) ||
    /^audio\//i.test(mimeType) ||
    /mp2t/i.test(mimeType)
  )
    return null;
  const mime = mimeType.toLowerCase();
  if (HLS.test(url) || mime.includes("mpegurl")) return "hls";
  if (DASH.test(url) || mime.includes("dash+xml")) return "dash";
  if (MEDIA_EXTENSIONS.test(url) || mime.startsWith("video/")) return "direct";
  return null;
}

export function originPatterns(discovery: DiscoveryResult): string[] {
  return toOriginPatterns([
    ...pageUrls(discovery),
    ...discovery.media_candidates.map((item) => item.url),
    ...discovery.caption_candidates.flatMap((item) =>
      item.url ? [item.url] : [],
    ),
  ]);
}

/**
 * The origins of the page and the frame playing the video, leaving out the CDN and caption
 * hosts. The site's own cookies come from these; a CDN's cookies and caption bodies only
 * add to what the scan gets.
 */
export function pageOriginPatterns(discovery: DiscoveryResult): string[] {
  return toOriginPatterns(pageUrls(discovery));
}

function pageUrls(discovery: DiscoveryResult): string[] {
  return [discovery.frame_url || discovery.page_url, discovery.page_url];
}

function toOriginPatterns(urls: string[]): string[] {
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

export function chooseDirectCandidate(
  candidates: MediaCandidate[],
): MediaCandidate | undefined {
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

/** A provider host alone is not a downloadable video identity. */
export function youtubeVideoUrl(value: string): string | undefined {
  if (!isYouTubeUrl(value)) return;
  const url = new URL(value);
  if (!/^https?:$/.test(url.protocol)) return;
  const id = url.hostname === "youtu.be"
    ? url.pathname.split("/")[1]
    : url.searchParams.get("v") ||
      url.pathname.match(/^\/(?:embed|shorts|live)\/([\w-]+)(?:\/|$)/)?.[1];
  return id && /^[\w-]{11}$/.test(id)
    ? `https://www.youtube.com/watch?v=${id}`
    : undefined;
}

export type DrmSystem =
  "widevine" | "playready" | "fairplay" | "clearkey" | "drm";

export interface DrmCheck {
  drm_detected: boolean;
  system?: DrmSystem;
  reason?: string;
}

const WIDEVINE_SYSTEM_ID = "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed";
const PLAYREADY_SYSTEM_ID = "9a04f079-9840-4286-ab92-e65be0885f95";
const FAIRPLAY_KEYFORMAT = "com.apple.streamingkeydelivery";
const CLEARKEY_SYSTEM_ID = "1077efec-c0b2-4d02-ace3-3c1e52e2fb4b";

/**
 * Looks for the tags a manifest carries when its segments need a DRM license rather than
 * being merely obfuscated. HLS's own `METHOD=AES-128` is a plain static key yt-dlp already
 * fetches and decrypts on its own -- only `SAMPLE-AES` or a DRM `KEYFORMAT` mean a license
 * server is involved. DASH signals the same thing with a `ContentProtection` element.
 */
export function detectManifestDrm(text: string, kind: MediaKind): DrmCheck {
  if (kind === "hls") {
    const keyLines = text.match(/#EXT-X-KEY:[^\r\n]*/gi) ?? [];
    for (const line of keyLines) {
      const method = /METHOD=([\w-]+)/i.exec(line)?.[1]?.toUpperCase();
      if (!method || method === "NONE" || method === "AES-128") continue;
      const keyformat =
        /KEYFORMAT="([^"]+)"/i.exec(line)?.[1]?.toLowerCase() ?? "";
      if (keyformat.includes(WIDEVINE_SYSTEM_ID)) {
        return {
          drm_detected: true,
          system: "widevine",
          reason: "HLS EXT-X-KEY uses Widevine",
        };
      }
      if (keyformat.includes(FAIRPLAY_KEYFORMAT)) {
        return {
          drm_detected: true,
          system: "fairplay",
          reason: "HLS EXT-X-KEY uses FairPlay",
        };
      }
      if (keyformat.includes(CLEARKEY_SYSTEM_ID)) {
        return {
          drm_detected: true,
          system: "clearkey",
          reason: "HLS EXT-X-KEY uses ClearKey",
        };
      }
      return {
        drm_detected: true,
        system: "drm",
        reason: `HLS EXT-X-KEY method ${method}`,
      };
    }
    return { drm_detected: false };
  }
  if (kind === "dash") {
    if (!/<ContentProtection[\s>]/i.test(text)) return { drm_detected: false };
    const lowered = text.toLowerCase();
    if (lowered.includes(WIDEVINE_SYSTEM_ID)) {
      return {
        drm_detected: true,
        system: "widevine",
        reason: "DASH ContentProtection uses Widevine",
      };
    }
    if (lowered.includes(PLAYREADY_SYSTEM_ID)) {
      return {
        drm_detected: true,
        system: "playready",
        reason: "DASH ContentProtection uses PlayReady",
      };
    }
    if (lowered.includes(CLEARKEY_SYSTEM_ID)) {
      return {
        drm_detected: true,
        system: "clearkey",
        reason: "DASH ContentProtection uses ClearKey",
      };
    }
    return {
      drm_detected: true,
      system: "drm",
      reason: "DASH manifest declares ContentProtection",
    };
  }
  return { drm_detected: false };
}

const LICENSE_TRAFFIC =
  /license|widevine|playready|fairplay|drmtoday|castlabs|\/drm\/|getlicense|acquirelicense/i;

/** A request to one of these looks like a DRM license acquisition, not the media itself. */
export function isLicenseTraffic(url: string): boolean {
  return LICENSE_TRAFFIC.test(url);
}

export interface EmeMonitorState {
  requested: boolean;
  keySystem?: string;
  encryptedEventFired: boolean;
  setMediaKeysCalled: boolean;
}

/**
 * Injected into the page's MAIN world (not the isolated content-script world) so it patches
 * the very `navigator`/`HTMLMediaElement` the player itself calls. A manifest can look clean
 * while the player still switches to a DRM-protected rendition once playback starts, so this
 * is the only way to observe that. Idempotent: installing it twice keeps the first instance.
 */
export function installEmeMonitor(): void {
  const globalWithMonitor = window as unknown as {
    __vidseekEmeMonitor?: EmeMonitorState;
  };
  if (globalWithMonitor.__vidseekEmeMonitor) return;
  const state: EmeMonitorState = {
    requested: false,
    encryptedEventFired: false,
    setMediaKeysCalled: false,
  };
  globalWithMonitor.__vidseekEmeMonitor = state;

  const originalRequest =
    navigator.requestMediaKeySystemAccess?.bind(navigator);
  if (originalRequest) {
    navigator.requestMediaKeySystemAccess = (keySystem, configs) => {
      state.requested = true;
      state.keySystem = keySystem;
      return originalRequest(keySystem, configs);
    };
  }

  const mediaElementProto = window.HTMLMediaElement?.prototype;
  const originalSetMediaKeys = mediaElementProto?.setMediaKeys;
  if (mediaElementProto && typeof originalSetMediaKeys === "function") {
    mediaElementProto.setMediaKeys = function (
      this: HTMLMediaElement,
      mediaKeys,
    ) {
      if (mediaKeys) state.setMediaKeysCalled = true;
      return originalSetMediaKeys.call(this, mediaKeys);
    };
  }

  // `encrypted` does not bubble, but capture-phase delivery still visits every ancestor
  // regardless of a target's bubbling, so one listener on `document` sees every element.
  document.addEventListener(
    "encrypted",
    () => {
      state.encryptedEventFired = true;
    },
    true,
  );
}

/** Reads back what `installEmeMonitor` observed; also injected into the MAIN world. */
export function readEmeMonitor(): EmeMonitorState | undefined {
  return (window as unknown as { __vidseekEmeMonitor?: EmeMonitorState })
    .__vidseekEmeMonitor;
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
export function mergeDiscoveryResults(
  frames: FrameDiscoveryResult[],
): DiscoveryResult | undefined {
  const originalFrames = frames;
  frames = expandVideoFrames(frames);
  const usable = frames.filter(
    (f) => f.result && !isEmptyFrameResult(f.result),
  );
  if (usable.length === 1)
    return resolveSelectedGroup(
      { frameId: usable[0]!.frameId, label: "", result: usable[0]!.result! },
      originalFrames,
    );
  if (frames.length === 1) return frames[0]?.result;
  const withResult = frames.filter(
    (frame): frame is FrameDiscoveryResult & { result: DiscoveryResult } =>
      Boolean(frame.result),
  );
  const first = withResult[0];
  if (!first) return undefined;
  const youtubeFrame = withResult.find((frame) =>
    isYouTubeUrl(frame.result.page_url),
  );
  if (youtubeFrame) return youtubeFrame.result;
  const top = withResult.find((frame) => frame.frameId === 0) ?? first;

  const media = new Map<string, MediaCandidate>();
  const captions = new Map<
    string,
    DiscoveryResult["caption_candidates"][number]
  >();
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
    caption_candidates: [...captions.values()].slice(0, MAX_CAPTION_CANDIDATES),
  };
}

/** One frame's worth of candidates, offered to the user as a single choice of video. */
function expandVideoFrames(
  frames: FrameDiscoveryResult[],
): FrameDiscoveryResult[] {
  const result: FrameDiscoveryResult[] = [];
  for (const frame of frames) {
    for (let item of frame.result?.videos ||
      (frame.result ? [frame.result] : [])) {
      const canonical = youtubeVideoUrl(item.page_url);
      if (canonical && canonical !== item.page_url)
        item = { ...item, page_url: canonical };
      const duplicate = result.find(
        (f) =>
          isYouTubeUrl(item.page_url) && f.result?.page_url === item.page_url,
      );
      if (duplicate) {
        // The full player's title is more useful than its search page's thumbnail
        // title. Its frame also remains the right owner for subsequent inspection.
        const playerFrame = isYouTubeUrl(item.frame_url || "");
        const duplicatePlayerFrame = isYouTubeUrl(duplicate.result?.frame_url || "");
        if ((playerFrame && !duplicatePlayerFrame) || item.caption_candidates.length) {
          duplicate.result = item;
          duplicate.frameId = frame.frameId;
        }
      } else result.push({ frameId: frame.frameId, result: item });
    }
  }
  return result;
}

export interface VideoGroup {
  frameId: number;
  label: string;
  /** A second, quieter line under the label: what sets this choice apart. */
  detail?: string;
  /** The choice most likely to be the video the user means; the picker selects it first. */
  recommended?: boolean;
  result: DiscoveryResult;
}

/** 754 → "12:34", 4000 → "1:06:40". */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.round(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}`
    : `${minutes}:${rest}`;
}

export interface CapturedSourceChoice {
  candidate: MediaCandidate;
  label: string;
  detail: string;
  recommended: boolean;
}

// A clip this short, and this much shorter than the longest one seen, is almost never the
// video the user came for.
const SHORT_CLIP_SECONDS = 90;
const SHORT_CLIP_RATIO = 3;
// Less than this is the player buffering ahead, not the user watching.
const MIN_PLAYED_SECONDS = 1;

/**
 * Names the videos a playback check captured, longest first. A stream carries no title, and
 * a URL means nothing to the user, so each is marked by what they can recognise: whether
 * they played it during the check, and how long it runs (the talk runs for minutes, the ad
 * or sponsor intro before it for seconds).
 */
export function describeCapturedSources(
  candidates: MediaCandidate[],
  pageTitle?: string,
): CapturedSourceChoice[] {
  const ordered = [...candidates].sort(
    (left, right) =>
      (right.duration_seconds ?? -1) - (left.duration_seconds ?? -1),
  );
  const longest = ordered[0]?.duration_seconds;
  const measured = ordered.filter((candidate) => candidate.duration_seconds);
  const played = (candidate: MediaCandidate): boolean =>
    (candidate.played_seconds ?? 0) >= MIN_PLAYED_SECONDS;
  const anyPlayed = ordered.some(played);
  // Without lengths to compare, the one the user played the most is the best guess.
  const mostPlayed = ordered.reduce<MediaCandidate | undefined>(
    (best, candidate) =>
      played(candidate) &&
      (candidate.played_seconds ?? 0) > (best?.played_seconds ?? 0)
        ? candidate
        : best,
    undefined,
  );
  return ordered.map((candidate, index) => {
    const duration = candidate.duration_seconds;
    const facts = [duration ? formatDuration(duration) : "length unknown"];
    if (candidate.max_height) facts.push(`up to ${candidate.max_height}p`);

    const marks: string[] = [];
    if (played(candidate))
      marks.push(`You played ${formatDuration(candidate.played_seconds!)} of it`);
    else if (anyPlayed) marks.push("Not played during the check");
    const recommended =
      measured.length > 1 ? index === 0 : candidate === mostPlayed;
    if (recommended && measured.length > 1)
      marks.push("longest, most likely the main video");
    else if (
      measured.length > 1 &&
      longest &&
      duration &&
      duration < SHORT_CLIP_SECONDS &&
      duration * SHORT_CLIP_RATIO <= longest
    )
      marks.push("short, probably an ad or intro");
    const detail = marks.length
      ? capitalize(marks.join(", "))
      : `Streamed from ${hostnameOf(candidate.url)}`;
    return {
      candidate,
      label: `${pageTitle ? `${pageTitle} · Source` : "Video"} ${index + 1} · ${facts.join(" · ")}`,
      detail,
      recommended,
    };
  });
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "this page";
  }
}

function isEmptyFrameResult(result: DiscoveryResult): boolean {
  return (
    !isYouTubeUrl(result.page_url) &&
    result.media_candidates.length === 0 &&
    result.caption_candidates.length === 0 &&
    !result.structured_candidates?.length
  );
}

/**
 * The video's own title where the page gives it one (structured data, an aria-label, an
 * embed's document title), retaining the page title when that is all we have.
 * Repeated titles are numbered by findVideoGroups; details distinguish their sources.
 */
function describeVideoGroup(
  result: DiscoveryResult,
  position: number,
): string {
  if (isYouTubeUrl(result.page_url))
    return `YouTube: ${result.page_title.replace(/ - YouTube$/, "")}`;
  if (result.page_title)
    return result.page_title;
  return `Video ${position}`;
}

/** What the user can check against the page: is it the one playing, how long, and where. */
function describeVideoGroupDetail(
  result: DiscoveryResult,
  frameId: number,
): string {
  const marks: string[] = [];
  if (result.media_playing) marks.push("Playing now");
  const duration = result.media_duration_seconds;
  if (duration && Number.isFinite(duration)) marks.push(formatDuration(duration));
  if (frameId === 0 || isYouTubeUrl(result.page_url)) {
    if (!marks.length) marks.push("In the page itself");
  } else {
    marks.push(
      `embedded from ${hostnameOf(result.frame_url || result.page_url)}`,
    );
  }
  return capitalize(marks.join(" · "));
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
export function findVideoGroups(
  frames: FrameDiscoveryResult[],
  topPageTitle: string,
): VideoGroup[] | undefined {
  frames = expandVideoFrames(frames);
  const groups = frames
    .filter(
      (frame): frame is FrameDiscoveryResult & { result: DiscoveryResult } =>
        Boolean(frame.result),
    )
    .filter((frame) => !isEmptyFrameResult(frame.result))
    .map((frame, index) => ({
      frameId: frame.frameId,
      label: describeVideoGroup(frame.result, index + 1),
      detail: describeVideoGroupDetail(frame.result, frame.frameId),
      recommended: Boolean(frame.result.media_playing),
      result: frame.result,
    }));
  // Two videos carrying the same title still need telling apart.
  const labels = groups.map((group) => group.label);
  for (const [index, group] of groups.entries()) {
    if (labels.filter((label) => label === group.label).length > 1)
      group.label = `${group.label} (${index + 1})`;
  }
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
export function resolveSelectedGroup(
  group: VideoGroup,
  frames: FrameDiscoveryResult[],
): DiscoveryResult {
  if (isYouTubeUrl(group.result.page_url))
    return group.result.selected_media_id
      ? { ...group.result, selected_media_id: undefined }
      : group.result;
  const top = frames.find((frame) => frame.frameId === 0)?.result;
  if (!top) return group.result;
  return {
    ...group.result,
    frame_url: group.result.frame_url || group.result.page_url,
    page_url: top.page_url,
    page_title: group.result.selected_media_id
      ? group.result.page_title
      : top.page_title,
    preferred_language:
      group.result.preferred_language || top.preferred_language,
    drm_detected: group.result.drm_detected,
    media_candidates: group.result.media_candidates,
    caption_candidates: group.result.caption_candidates,
  };
}

export { discoverPage } from "./page-discovery";
