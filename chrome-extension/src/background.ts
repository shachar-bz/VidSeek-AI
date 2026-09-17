import { cancelJob, getHealth, getJob, reportBrowserDownload, retryWithCapture } from "./api";
import { classifyMediaUrl, detectManifestDrm, installEmeMonitor, isLicenseTraffic, readEmeMonitor } from "./discovery";
import type { BrowserCookie, ExtensionMessage, MediaCandidate, StopCaptureResult, TrackedJob } from "./types";

// Makes the action button open the side panel directly, matching a normal popup's click
// behavior instead of requiring the user to right-click and pick "Open side panel".
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);

const TRACKER_KEY = "activeVideoJob";
const CAPTURE_KEY = "activeCapture";
const LAST_ERROR_KEY = "lastJobError";
const POLL_ALARM = "vidseek-job-poll";
const TERMINAL = new Set(["complete", "partial_success", "cancelled"]);

/** The folder a path sits in, comparing forward and back slashes alike. */
function parentFolder(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const index = normalized.lastIndexOf("/");
  return index === -1 ? normalized : normalized.slice(0, index);
}

/**
 * When the companion rejects a Chrome download as outside `VIDSEEK_DOWNLOAD_ROOT`, the
 * generic error says so but not where either side actually points. Comparing Chrome's
 * real save folder against the companion's configured root turns that into something the
 * user can act on instead of a bare "!" badge.
 */
async function describeDownloadRootMismatch(chromeDownloadPath: string): Promise<string | undefined> {
  const health = await getHealth().catch(() => undefined);
  if (!health?.download_root) return undefined;
  const chromeFolder = parentFolder(chromeDownloadPath);
  const companionRoot = parentFolder(`${health.download_root}/x`);
  if (chromeFolder.toLowerCase() === companionRoot.toLowerCase()) return undefined;
  return (
    `Chrome saved the download to "${chromeFolder}", but VidSeek expects "${companionRoot}". ` +
    "Change Chrome's download location (chrome://settings/downloads) or set VIDSEEK_DOWNLOAD_ROOT " +
    "to match, then try again."
  );
}

async function setLastJobError(message: string): Promise<void> {
  await chrome.storage.session.set({ [LAST_ERROR_KEY]: message });
  await chrome.action.setTitle({ title: message });
}

interface CapturedRequest {
  url: string;
  headers: Record<string, string>;
  resourceType?: string;
  mimeType?: string;
}

interface CaptureState {
  tabId: number;
  // Absent for a pre-download DRM verification: it runs before any job exists to retry.
  jobId?: string;
  requests: Map<string, CapturedRequest>;
  pendingHeaders: Map<string, Record<string, string>>;
}

/** `CaptureState` with its Maps flattened, because storage only holds plain JSON. */
interface StoredCapture {
  tabId: number;
  jobId?: string;
  requests: [string, CapturedRequest][];
  pendingHeaders: [string, Record<string, string>][];
}

/**
 * A capture spans a popup close and reopen by design, and the service worker is torn
 * down after ~30s of idleness in between. The in-memory copy is therefore only a cache
 * in front of `chrome.storage.session`, which is what actually survives the restart.
 */
let captureCache: CaptureState | null = null;

async function readCapture(): Promise<CaptureState | null> {
  if (captureCache) return captureCache;
  const stored = (await chrome.storage.session.get(CAPTURE_KEY))[CAPTURE_KEY] as
    | StoredCapture
    | undefined;
  if (!stored) return null;
  captureCache = {
    tabId: stored.tabId,
    jobId: stored.jobId,
    requests: new Map(stored.requests),
    pendingHeaders: new Map(stored.pendingHeaders)
  };
  return captureCache;
}

async function writeCapture(state: CaptureState): Promise<void> {
  captureCache = state;
  const stored: StoredCapture = {
    tabId: state.tabId,
    jobId: state.jobId,
    requests: [...state.requests],
    pendingHeaders: [...state.pendingHeaders]
  };
  await chrome.storage.session.set({ [CAPTURE_KEY]: stored });
}

async function clearCapture(): Promise<void> {
  captureCache = null;
  await chrome.storage.session.remove(CAPTURE_KEY);
  await chrome.action.setBadgeText({ text: "" });
}

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
  await chrome.storage.session.remove([TRACKER_KEY, LAST_ERROR_KEY]);
  await chrome.alarms.clear(POLL_ALARM);
  await chrome.action.setBadgeText({ text: "" });
  await chrome.action.setTitle({ title: "" });
}

async function pollTrackedJob(): Promise<void> {
  const tracker = await readTracker();
  if (!tracker) {
    // Alarms survive a browser restart but session storage does not, so an orphaned
    // alarm would otherwise wake the worker every 30 seconds forever.
    await chrome.alarms.clear(POLL_ALARM);
    return;
  }
  try {
    const job = await getJob(tracker.token, tracker.jobId);
    if (TERMINAL.has(job.status)) {
      await cleanupTracker(tracker);
      return;
    }
    // "failed" is not terminal while the user can still retry with a debugger capture.
    if (job.status === "failed" && !job.can_capture) {
      await cleanupTracker(tracker);
      await chrome.action.setBadgeText({ text: "!" });
      return;
    }
    await chrome.action.setBadgeText({
      text: job.status === "failed" ? "!" : String(Math.round(job.progress * 100))
    });
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
    try {
      await reportBrowserDownload(tracker.token, tracker.jobId, item.filename);
    } catch (error) {
      // downloads.onChanged fires once, so there is no second chance to hand the file
      // over. Leaving the job in awaiting_browser_download would strand it silently.
      const mismatch = await describeDownloadRootMismatch(item.filename);
      await cancelJob(tracker.token, tracker.jobId).catch(() => undefined);
      await cleanupTracker(tracker);
      await setLastJobError(mismatch || String(error));
      await chrome.action.setBadgeText({ text: "!" });
      return;
    }
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
  // Stored first: a small or cached file can reach state "complete" before
  // downloads.download() resolves, and onChanged ignores an unknown download id.
  await writeTracker(tracker);
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

async function recordDebuggerEvent(
  source: chrome.debugger.Debuggee,
  method: string,
  params?: object
): Promise<void> {
  const current = await readCapture();
  if (!current || source.tabId !== current.tabId) return;
  const data = (params ?? {}) as Record<string, any>;
  const requestId = String(data.requestId || "");
  if (!requestId) return;
  if (method === "Network.requestWillBeSent") {
    const request = data.request as { url?: string; headers?: Record<string, unknown> } | undefined;
    if (!request?.url) return;
    current.requests.set(requestId, {
      url: request.url,
      headers: {
        ...filterCapturedHeaders(request.headers || {}),
        ...(current.pendingHeaders.get(requestId) || {})
      },
      resourceType: String(data.type || "")
    });
    current.pendingHeaders.delete(requestId);
  } else if (method === "Network.requestWillBeSentExtraInfo") {
    const existing = current.requests.get(requestId);
    if (existing) {
      existing.headers = { ...existing.headers, ...filterCapturedHeaders(data.headers || {}) };
    } else {
      current.pendingHeaders.set(requestId, filterCapturedHeaders(data.headers || {}));
    }
  } else if (method === "Network.responseReceived") {
    const existing = current.requests.get(requestId);
    if (existing) {
      existing.mimeType = String(data.response?.mimeType || "");
      existing.resourceType = String(data.type || existing.resourceType || "");
    } else {
      return;
    }
  } else {
    return;
  }
  await writeCapture(current);
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  void recordDebuggerEvent(source, method, params);
});

chrome.debugger.onDetach.addListener((source) => {
  // The user can dismiss Chrome's debugging infobar, and a closed tab detaches too.
  void (async () => {
    const current = await readCapture();
    if (current && source.tabId === current.tabId) await clearCapture();
  })();
});

async function startCapture(tabId: number, jobId?: string): Promise<void> {
  if (await readCapture()) throw new Error("A capture is already active");
  await chrome.debugger.attach({ tabId }, "1.3");
  try {
    await chrome.debugger.sendCommand({ tabId }, "Network.enable", {
      maxTotalBufferSize: 1_000_000,
      maxResourceBufferSize: 100_000
    });
    // Best-effort: a page with a strict CSP can refuse the injection, and the network
    // capture alone still catches manifest- and license-based DRM signals without it.
    await chrome.scripting
      .executeScript({ target: { tabId, allFrames: true }, world: "MAIN", func: installEmeMonitor })
      .catch(() => undefined);
    await writeCapture({ tabId, jobId, requests: new Map(), pendingHeaders: new Map() });
    await chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
    // Deliberately not scoped to the tab: a per-tab badge outranks the global progress
    // badge and would survive a worker restart with nothing left to clear it.
    await chrome.action.setBadgeText({ text: "REC" });
  } catch (error) {
    await chrome.debugger.detach({ tabId }).catch(() => undefined);
    throw error;
  }
}

function buildCandidatesFromRequests(requests: Map<string, CapturedRequest>): {
  candidates: MediaCandidate[];
  cookies: BrowserCookie[];
} {
  const candidates: MediaCandidate[] = [];
  const capturedCookies = new Map<string, BrowserCookie>();
  const seen = new Set<string>();
  for (const request of requests.values()) {
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
  return { candidates, cookies: [...capturedCookies.values()] };
}

/**
 * Checks every signal a debugger capture can see for DRM: a manifest body (only readable
 * while still attached, hence this runs before `chrome.debugger.detach`), a request to a
 * known license endpoint, and whatever `installEmeMonitor` observed in the page itself.
 */
async function detectDrmInCapture(current: CaptureState): Promise<{ drm_detected: boolean; reason?: string }> {
  for (const request of current.requests.values()) {
    if (isLicenseTraffic(request.url)) {
      return { drm_detected: true, reason: `A DRM license request was observed: ${request.url}` };
    }
  }
  for (const [requestId, request] of current.requests) {
    const kind = classifyMediaUrl(request.url, request.mimeType || "");
    if (kind !== "hls" && kind !== "dash") continue;
    try {
      const response = (await chrome.debugger.sendCommand({ tabId: current.tabId }, "Network.getResponseBody", {
        requestId
      })) as { body: string; base64Encoded: boolean };
      const text = response.base64Encoded ? atob(response.body) : response.body;
      const check = detectManifestDrm(text, kind);
      if (check.drm_detected) return { drm_detected: true, reason: check.reason };
    } catch {
      // The debugger evicts buffered bodies under memory pressure; not fatal to the check.
    }
  }
  const emeResults = await chrome.scripting
    .executeScript({ target: { tabId: current.tabId, allFrames: true }, world: "MAIN", func: readEmeMonitor })
    .catch(() => []);
  // `requested` alone is not decisive: several player libraries probe EME support up front
  // even for content with no DRM at all. Only an attached key or an `encrypted` event means
  // the pipeline actually switched to protected media.
  const eme = emeResults.map((frame) => frame.result).find((state) => state?.encryptedEventFired || state?.setMediaKeysCalled);
  if (eme) {
    return { drm_detected: true, reason: `The player activated DRM${eme.keySystem ? ` (${eme.keySystem})` : ""}` };
  }
  return { drm_detected: false };
}

async function stopCapture(): Promise<StopCaptureResult> {
  const current = await readCapture();
  if (!current) throw new Error("No capture is active");

  const drm = await detectDrmInCapture(current);
  await clearCapture();
  await chrome.debugger.detach({ tabId: current.tabId }).catch(() => undefined);

  if (drm.drm_detected) {
    if (current.jobId) {
      const tracker = await readTracker();
      if (tracker && tracker.jobId === current.jobId) {
        await cancelJob(tracker.token, tracker.jobId).catch(() => undefined);
        await cleanupTracker(tracker);
      }
    }
    await chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
    await chrome.action.setBadgeText({ text: "DRM" });
    return { drm_detected: true, reason: drm.reason, candidates: [] };
  }

  const { candidates, cookies } = buildCandidatesFromRequests(current.requests);
  if (!candidates.length) throw new Error("No media request was captured; reload and play the video before stopping");
  if (current.jobId) {
    const tracker = await readTracker();
    if (!tracker || tracker.jobId !== current.jobId) throw new Error("Captured job is no longer active");
    await retryWithCapture(tracker.token, tracker.jobId, candidates.slice(0, 25), {
      cookies,
      headers: {},
      user_agent: navigator.userAgent
    });
  }
  return { drm_detected: false, candidates: candidates.slice(0, 25) };
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
      case "GET_TRACKED_JOB": {
        const current = await readCapture();
        const lastError = (await chrome.storage.session.get(LAST_ERROR_KEY))[LAST_ERROR_KEY] as
          | string
          | undefined;
        return {
          ok: true,
          tracker: await readTracker(),
          // A capture with no jobId is a pre-download DRM verification, not a job retry.
          capturing: Boolean(current?.jobId),
          verifying: Boolean(current) && !current?.jobId,
          lastError
        };
      }
      case "CANCEL_TRACKED_JOB": {
        const tracker = await readTracker();
        if (tracker) {
          if (tracker.downloadId) await chrome.downloads.cancel(tracker.downloadId).catch(() => undefined);
          await cancelJob(tracker.token, tracker.jobId).catch(() => undefined);
          await cleanupTracker(tracker);
        }
        const current = await readCapture();
        if (current) {
          await chrome.debugger.detach({ tabId: current.tabId }).catch(() => undefined);
          await clearCapture();
        }
        return { ok: true };
      }
      case "START_CAPTURE":
        await startCapture(message.tabId, message.jobId);
        return { ok: true };
      case "STOP_CAPTURE":
        return { ok: true, ...(await stopCapture()) };
    }
  })()
    .then(sendResponse)
    .catch((error: unknown) => sendResponse({ ok: false, error: String(error) }));
  return true;
});

void pollTrackedJob();
