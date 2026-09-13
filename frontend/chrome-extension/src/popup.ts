import { createJob, createSession, getJob } from "./api";
import { chooseDirectCandidate, discoverPage, originPatterns } from "./discovery";
import type {
  BrowserContext,
  DiscoveryResult,
  ExtensionMessage,
  TrackedJob,
  VideoJob
} from "./types";

const statusElement = document.querySelector<HTMLParagraphElement>("#status")!;
const detailsElement = document.querySelector<HTMLDivElement>("#details")!;
const progressElement = document.querySelector<HTMLProgressElement>("#progress")!;
const inspectButton = document.querySelector<HTMLButtonElement>("#inspect")!;
const downloadButton = document.querySelector<HTMLButtonElement>("#download")!;
const captureButton = document.querySelector<HTMLButtonElement>("#capture")!;
const stopCaptureButton = document.querySelector<HTMLButtonElement>("#stop-capture")!;
const cancelButton = document.querySelector<HTMLButtonElement>("#cancel")!;

let discovery: DiscoveryResult | undefined;
let activeTabId: number | undefined;
let pollingTimer: number | undefined;

function setStatus(message: string, details = ""): void {
  statusElement.textContent = message;
  detailsElement.textContent = details;
}

function message<T = Record<string, unknown>>(payload: ExtensionMessage): Promise<T> {
  return chrome.runtime.sendMessage(payload) as Promise<T>;
}

async function inspectTab(): Promise<void> {
  inspectButton.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url?.startsWith("http")) throw new Error("Open an HTTP or HTTPS video page first");
    activeTabId = tab.id;
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: discoverPage
    });
    discovery = results[0]?.result as DiscoveryResult | undefined;
    if (!discovery) throw new Error("The page could not be inspected");
    if (/^(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)(?:\/|$)/i.test(discovery.page_url)) {
      throw new Error("Use VidSeek's YouTube pipeline for this page");
    }
    if (discovery.drm_detected) throw new Error("This player reports DRM protection and cannot be downloaded");
    if (!discovery.media_candidates.length) {
      setStatus(
        "No direct source found yet.",
        "You can still submit the page to its yt-dlp extractor; capture is available if that fails."
      );
    } else {
      setStatus(
        "Video discovered.",
        `${discovery.media_candidates.length} media source(s), ${discovery.caption_candidates.length} caption/transcript source(s)`
      );
    }
    downloadButton.hidden = false;
  } catch (error) {
    setStatus("Inspection failed", String(error));
  } finally {
    inspectButton.disabled = false;
  }
}

async function collectCookies(discoveryValue: DiscoveryResult): Promise<BrowserContext> {
  const cookies = new Map<string, chrome.cookies.Cookie>();
  const urls = [
    discoveryValue.page_url,
    ...discoveryValue.media_candidates.map((candidate) => candidate.url),
    ...discoveryValue.caption_candidates.flatMap((candidate) => (candidate.url ? [candidate.url] : []))
  ];
  for (const url of urls) {
    if (!url.startsWith("http")) continue;
    for (const cookie of await chrome.cookies.getAll({ url })) {
      cookies.set(`${cookie.storeId}|${cookie.domain}|${cookie.path}|${cookie.name}`, cookie);
    }
    try {
      const partitioned = await chrome.cookies.getAll({
        url,
        partitionKey: { topLevelSite: new URL(discoveryValue.page_url).origin }
      });
      for (const cookie of partitioned) {
        cookies.set(`${cookie.storeId}|${cookie.domain}|${cookie.path}|${cookie.name}`, cookie);
      }
    } catch {
      // Older supported Chrome builds may not expose partition-key lookup.
    }
  }
  return {
    cookies: [...cookies.values()].map((cookie) => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      http_only: cookie.httpOnly,
      expiration_date: cookie.expirationDate
    })),
    headers: {
      Referer: discoveryValue.page_url,
      Origin: new URL(discoveryValue.page_url).origin
    },
    user_agent: navigator.userAgent
  };
}

async function hydrateCaptionBodies(discoveryValue: DiscoveryResult): Promise<void> {
  for (const candidate of discoveryValue.caption_candidates) {
    if (!candidate.url || candidate.text) continue;
    try {
      const response = await fetch(candidate.url, { credentials: "include" });
      if (!response.ok) continue;
      const length = Number(response.headers.get("content-length") || 0);
      if (length > 5_000_000) continue;
      const text = await response.text();
      if (text.length <= 5_000_000) candidate.text = text;
    } catch {
      // yt-dlp or ElevenLabs remains available when a track cannot be read by JS.
    }
  }
}

async function startDownload(): Promise<void> {
  if (!discovery) return;
  downloadButton.disabled = true;
  let grantedOrigins: string[] = [];
  try {
    const origins = originPatterns(discovery);
    const granted = await chrome.permissions.request({ permissions: ["cookies"], origins });
    if (!granted) throw new Error("Site/CDN access was not granted");
    grantedOrigins = origins;
    await hydrateCaptionBodies(discovery);
    const context = await collectCookies(discovery);
    const token = await createSession();
    const job = await createJob(token, discovery, context);
    const tracker: TrackedJob = { jobId: job.job_id, token, grantedOrigins: origins };
    const direct = chooseDirectCandidate(discovery.media_candidates);
    if (job.acquisition_mode === "browser_download" && direct) {
      await message({
        type: "START_BROWSER_DOWNLOAD",
        tracker,
        url: direct.url,
        filename: discovery.page_title
      });
    } else {
      await message({ type: "TRACK_JOB", tracker });
    }
    downloadButton.hidden = true;
    inspectButton.hidden = true;
    cancelButton.hidden = false;
    renderJob(job);
    startPolling(tracker);
  } catch (error) {
    if (grantedOrigins.length) {
      await chrome.permissions.remove({ origins: grantedOrigins }).catch(() => false);
      await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
    }
    setStatus("Could not start download", String(error));
    downloadButton.disabled = false;
  }
}

function renderJob(job: VideoJob): void {
  progressElement.value = job.progress;
  setStatus(job.message, [job.video_path, job.transcript_text_path].filter(Boolean).join("\n"));
  captureButton.hidden = !job.can_capture;
  cancelButton.hidden = ["complete", "partial_success", "failed", "cancelled"].includes(job.status);
  if (["complete", "partial_success", "cancelled"].includes(job.status)) stopPolling();
}

function startPolling(tracker: TrackedJob): void {
  stopPolling();
  const poll = async (): Promise<void> => {
    try {
      renderJob(await getJob(tracker.token, tracker.jobId));
    } catch (error) {
      setStatus("Companion is unavailable", String(error));
    }
  };
  void poll();
  pollingTimer = window.setInterval(() => void poll(), 1500);
}

function stopPolling(): void {
  if (pollingTimer !== undefined) window.clearInterval(pollingTimer);
  pollingTimer = undefined;
}

async function restoreTrackedJob(): Promise<void> {
  const response = await message<{ ok: boolean; tracker?: TrackedJob; capturing?: boolean }>({
    type: "GET_TRACKED_JOB"
  });
  if (!response.tracker) return;
  inspectButton.hidden = true;
  downloadButton.hidden = true;
  cancelButton.hidden = false;
  captureButton.hidden = Boolean(response.capturing);
  stopCaptureButton.hidden = !response.capturing;
  startPolling(response.tracker);
}

inspectButton.addEventListener("click", () => void inspectTab());
downloadButton.addEventListener("click", () => void startDownload());
cancelButton.addEventListener("click", () => {
  void message({ type: "CANCEL_TRACKED_JOB" }).then(() => {
    stopPolling();
    setStatus("Cancelled");
    cancelButton.hidden = true;
  });
});
captureButton.addEventListener("click", () => {
  void (async () => {
    const tracked = await message<{ tracker?: TrackedJob }>({ type: "GET_TRACKED_JOB" });
    if (!tracked.tracker || activeTabId === undefined) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      activeTabId = tab?.id;
    }
    if (!tracked.tracker || activeTabId === undefined) throw new Error("No retryable job or active tab");
    await message({ type: "START_CAPTURE", tabId: activeTabId, jobId: tracked.tracker.jobId });
    captureButton.hidden = true;
    stopCaptureButton.hidden = false;
    setStatus("Capture active", "Reload or replay the video, then reopen this popup and stop capture.");
  })().catch((error) => setStatus("Could not start capture", String(error)));
});
stopCaptureButton.addEventListener("click", () => {
  stopCaptureButton.disabled = true;
  void message({ type: "STOP_CAPTURE" }).then((response: any) => {
    if (!response.ok) throw new Error(response.error);
    stopCaptureButton.hidden = true;
    setStatus("Captured request submitted", `${response.candidates} media request(s) found`);
  }).catch((error) => {
    stopCaptureButton.disabled = false;
    setStatus("Capture did not find a video", String(error));
  });
});

void restoreTrackedJob();
