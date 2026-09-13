import { cancelJob, getJob, reportBrowserDownload, retryWithCapture } from "./api";
import { classifyMediaUrl } from "./discovery";
import type { BrowserCookie, ExtensionMessage, MediaCandidate, TrackedJob } from "./types";

const TRACKER_KEY = "activeVideoJob";
const POLL_ALARM = "vidseek-job-poll";
const TERMINAL = new Set(["complete", "partial_success", "cancelled"]);

interface CapturedRequest {
  url: string;
  headers: Record<string, string>;
  resourceType?: string;
  mimeType?: string;
}

interface CaptureState {
  tabId: number;
  jobId: string;
  requests: Map<string, CapturedRequest>;
  pendingHeaders: Map<string, Record<string, string>>;
}

let capture: CaptureState | null = null;

async function readTracker(): Promise<TrackedJob | undefined> {
  const value = await chrome.storage.session.get(TRACKER_KEY);
  return value[TRACKER_KEY] as TrackedJob | undefined;
}

async function writeTracker(tracker: TrackedJob): Promise<void> {
  await chrome.storage.session.set({ [TRACKER_KEY]: tracker });
  await chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
}

async function cleanupTracker(tracker: TrackedJob): Promise<void> {
  if (tracker.grantedOrigins.length) {
    await chrome.permissions.remove({ origins: tracker.grantedOrigins }).catch(() => false);
  }
  await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
  await chrome.storage.session.remove(TRACKER_KEY);
  await chrome.alarms.clear(POLL_ALARM);
  await chrome.action.setBadgeText({ text: "" });
}

async function pollTrackedJob(): Promise<void> {
  const tracker = await readTracker();
  if (!tracker) return;
  try {
    const job = await getJob(tracker.token, tracker.jobId);
    const percent = String(Math.round(job.progress * 100));
    await chrome.action.setBadgeText({ text: TERMINAL.has(job.status) ? "" : percent });
    if (TERMINAL.has(job.status)) await cleanupTracker(tracker);
  } catch {
    // The popup will show connectivity/auth errors; keep the tracker for retry.
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) void pollTrackedJob();
});

chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state?.current) return;
  void (async () => {
    const tracker = await readTracker();
    if (!tracker || tracker.downloadId !== delta.id) return;
    if (delta.state?.current === "interrupted") {
      await cancelJob(tracker.token, tracker.jobId).catch(() => undefined);
      await chrome.action.setBadgeText({ text: "!" });
      return;
    }
    if (delta.state?.current !== "complete") return;
    const items = await chrome.downloads.search({ id: delta.id });
    const item = items[0];
    if (!item?.filename) return;
    await reportBrowserDownload(tracker.token, tracker.jobId, item.filename);
    await pollTrackedJob();
  })();
});

function safeFilename(title: string, url: string): string {
  const cleaned = title.replace(/[<>:"/\\|?*\u0000-\u001f]+/g, "-").replace(/[ .-]+$/g, "");
  let extension = ".mp4";
  try {
    const match = new URL(url).pathname.match(/\.(mp4|m4v|mov|webm|mkv|avi)$/i);
    if (match) extension = `.${match[1]?.toLowerCase()}`;
  } catch {
    // Keep the compatible default extension.
  }
  return `VidSeek/${(cleaned || "video").slice(0, 120)}-${Date.now()}${extension}`;
}

async function startBrowserDownload(
  tracker: TrackedJob,
  url: string,
  title: string
): Promise<number> {
  const downloadId = await chrome.downloads.download({
    url,
    filename: safeFilename(title, url),
    conflictAction: "uniquify",
    saveAs: false
  });
  tracker.downloadId = downloadId;
  await writeTracker(tracker);
  return downloadId;
}

const SAFE_CAPTURE_HEADERS = new Set([
  "accept",
  "accept-language",
  "authorization",
  "cookie",
  "origin",
  "referer",
  "user-agent"
]);

function filterCapturedHeaders(headers: Record<string, unknown>): Record<string, string> {
  const filtered: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    if (SAFE_CAPTURE_HEADERS.has(name.toLowerCase()) && typeof value === "string") {
      filtered[name] = value;
    }
  }
  return filtered;
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!capture || source.tabId !== capture.tabId) return;
  const data = params as Record<string, any>;
  const requestId = String(data.requestId || "");
  if (!requestId) return;
  if (method === "Network.requestWillBeSent") {
    const request = data.request as { url?: string; headers?: Record<string, unknown> } | undefined;
    if (!request?.url) return;
    capture.requests.set(requestId, {
      url: request.url,
      headers: {
        ...filterCapturedHeaders(request.headers || {}),
        ...(capture.pendingHeaders.get(requestId) || {})
      },
      resourceType: String(data.type || "")
    });
    capture.pendingHeaders.delete(requestId);
  } else if (method === "Network.requestWillBeSentExtraInfo") {
    const existing = capture.requests.get(requestId);
    if (existing) {
      existing.headers = { ...existing.headers, ...filterCapturedHeaders(data.headers || {}) };
    } else {
      capture.pendingHeaders.set(requestId, filterCapturedHeaders(data.headers || {}));
    }
  } else if (method === "Network.responseReceived") {
    const existing = capture.requests.get(requestId);
    if (existing) {
      existing.mimeType = String(data.response?.mimeType || "");
      existing.resourceType = String(data.type || existing.resourceType || "");
    }
  }
});

async function startCapture(tabId: number, jobId: string): Promise<void> {
  if (capture) throw new Error("A capture is already active");
  await chrome.debugger.attach({ tabId }, "1.3");
  try {
    await chrome.debugger.sendCommand({ tabId }, "Network.enable", {
      maxTotalBufferSize: 1_000_000,
      maxResourceBufferSize: 100_000
    });
    capture = { tabId, jobId, requests: new Map(), pendingHeaders: new Map() };
    await chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
    await chrome.action.setBadgeText({ tabId, text: "REC" });
  } catch (error) {
    await chrome.debugger.detach({ tabId }).catch(() => undefined);
    throw error;
  }
}

async function stopCapture(): Promise<number> {
  if (!capture) throw new Error("No capture is active");
  const current = capture;
  capture = null;
  await chrome.debugger.detach({ tabId: current.tabId }).catch(() => undefined);
  await chrome.action.setBadgeText({ tabId: current.tabId, text: "" });

  const candidates: MediaCandidate[] = [];
  const capturedCookies = new Map<string, BrowserCookie>();
  const seen = new Set<string>();
  for (const request of current.requests.values()) {
    const kind = classifyMediaUrl(request.url, request.mimeType || "");
    const likelyMediaType = ["Media", "Manifest"].includes(request.resourceType || "");
    if ((!kind && !likelyMediaType) || seen.has(request.url)) continue;
    seen.add(request.url);
    const headers = { ...request.headers };
    const cookieHeaderName = Object.keys(headers).find((name) => name.toLowerCase() === "cookie");
    if (cookieHeaderName) {
      try {
        const hostname = new URL(request.url).hostname;
        for (const pair of headers[cookieHeaderName]!.split(";")) {
          const separator = pair.indexOf("=");
          if (separator <= 0) continue;
          const name = pair.slice(0, separator).trim();
          const value = pair.slice(separator + 1).trim();
          capturedCookies.set(`${hostname}|${name}`, {
            name,
            value,
            domain: hostname,
            path: "/",
            secure: request.url.startsWith("https:"),
            http_only: false
          });
        }
      } catch {
        // A malformed URL is filtered by the companion.
      }
      delete headers[cookieHeaderName];
    }
    candidates.push({
      kind: kind || "direct",
      url: request.url,
      mime_type: request.mimeType || "",
      source: "debugger",
      headers
    });
  }
  candidates.sort((left, right) => {
    const order = { hls: 0, dash: 1, direct: 2 };
    return order[left.kind] - order[right.kind];
  });
  const tracker = await readTracker();
  if (!tracker || tracker.jobId !== current.jobId) throw new Error("Captured job is no longer active");
  if (!candidates.length) throw new Error("No media request was captured; reload and play the video before stopping");
  await retryWithCapture(tracker.token, tracker.jobId, candidates.slice(0, 25), {
    cookies: [...capturedCookies.values()],
    headers: {},
    user_agent: navigator.userAgent
  });
  return candidates.length;
}

chrome.runtime.onMessage.addListener((message: ExtensionMessage, _sender, sendResponse) => {
  void (async () => {
    switch (message.type) {
      case "TRACK_JOB":
        await writeTracker(message.tracker);
        return { ok: true };
      case "START_BROWSER_DOWNLOAD": {
        const id = await startBrowserDownload(message.tracker, message.url, message.filename);
        return { ok: true, downloadId: id };
      }
      case "GET_TRACKED_JOB":
        return { ok: true, tracker: await readTracker(), capturing: Boolean(capture) };
      case "CANCEL_TRACKED_JOB": {
        const tracker = await readTracker();
        if (tracker) {
          if (tracker.downloadId) await chrome.downloads.cancel(tracker.downloadId).catch(() => undefined);
          await cancelJob(tracker.token, tracker.jobId).catch(() => undefined);
          await cleanupTracker(tracker);
        }
        return { ok: true };
      }
      case "START_CAPTURE":
        await startCapture(message.tabId, message.jobId);
        return { ok: true };
      case "STOP_CAPTURE":
        return { ok: true, candidates: await stopCapture() };
    }
  })()
    .then(sendResponse)
    .catch((error: unknown) => sendResponse({ ok: false, error: String(error) }));
  return true;
});

void pollTrackedJob();
