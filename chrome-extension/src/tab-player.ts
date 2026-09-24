// Reads and moves the playhead of the video playing in the active tab.
import { isYouTubeUrl } from "./discovery";

export interface PlayerPosition {
  seconds: number;
  paused: boolean;
}

/**
 * Whether two URLs show the same video: the same `v` on YouTube, where the page carries a
 * start time and a playlist in its query, and the same origin and path everywhere else.
 */
export function isSameVideoPage(left: string, right: string): boolean {
  try {
    const a = new URL(left);
    const b = new URL(right);
    if (isYouTubeUrl(left) && isYouTubeUrl(right)) {
      const id = (url: URL) =>
        url.searchParams.get("v") ??
        (url.hostname === "youtu.be" ? url.pathname.slice(1) : url.pathname);
      return id(a) === id(b);
    }
    return a.origin === b.origin && a.pathname === b.pathname;
  } catch {
    return false;
  }
}

interface FramePlayer extends PlayerPosition {
  area: number;
}

/** Runs in the page: the frame's largest loaded video, by on-screen area. */
function readLargestVideo(): FramePlayer | null {
  let best: FramePlayer | null = null;
  for (const video of document.querySelectorAll("video")) {
    if (video.readyState === 0) continue;
    const box = video.getBoundingClientRect();
    const area = box.width * box.height;
    if (!best || area > best.area)
      best = { area, seconds: video.currentTime, paused: video.paused };
  }
  return best;
}

/** Runs in the page: moves the frame's largest loaded video to `seconds`. */
function seekLargestVideo(seconds: number): boolean {
  let best: HTMLVideoElement | null = null;
  let bestArea = -1;
  for (const video of document.querySelectorAll("video")) {
    if (video.readyState === 0) continue;
    const box = video.getBoundingClientRect();
    if (box.width * box.height > bestArea) {
      best = video;
      bestArea = box.width * box.height;
    }
  }
  if (!best) return false;
  best.currentTime = seconds;
  return true;
}

/** The active tab, when it is still showing `pageUrl`. */
async function videoTab(pageUrl: string): Promise<chrome.tabs.Tab | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id !== undefined && tab.url && isSameVideoPage(tab.url, pageUrl)
    ? tab
    : undefined;
}

/** The frame holding the page's main player: the one whose largest video is largest. */
async function mainPlayer(
  tabId: number,
): Promise<{ frameId: number; player: FramePlayer } | undefined> {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: readLargestVideo,
  });
  let best: { frameId: number; player: FramePlayer } | undefined;
  for (const { frameId, result } of results) {
    if (result && (!best || result.area > best.player.area))
      best = { frameId, player: result };
  }
  return best;
}

/**
 * Where the video in the active tab stands, when that tab is the scanned video's page.
 * Null whenever it cannot tell — another page, no access to the tab, nothing loaded — which
 * is a question sent without a position rather than a failure.
 */
export async function readPlayerPosition(
  pageUrl: string,
): Promise<PlayerPosition | null> {
  try {
    const tab = await videoTab(pageUrl);
    if (!tab?.id) return null;
    const found = await mainPlayer(tab.id);
    return found
      ? { seconds: found.player.seconds, paused: found.player.paused }
      : null;
  } catch {
    return null;
  }
}

/** Seeks the video in the active tab. False when that tab is not the video's page. */
export async function seekPlayer(
  pageUrl: string,
  seconds: number,
): Promise<boolean> {
  try {
    const tab = await videoTab(pageUrl);
    if (!tab?.id) return false;
    const found = await mainPlayer(tab.id);
    if (!found) return false;
    const [outcome] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [found.frameId] },
      func: seekLargestVideo,
      args: [seconds],
    });
    return Boolean(outcome?.result);
  } catch {
    return false;
  }
}
