import { createJob, createSession, getJob } from "./api";
import { chooseDirectCandidate, discoverPage, isYouTubeUrl, mergeDiscoveryResults, originPatterns } from "./discovery";
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

    // Decided from the tab's own URL, before any script runs in the page. Discovery would
    // find nothing usable on YouTube anyway — its media URLs are expiring googlevideo
    // links — and the YouTube player reports DRM on streams the pipeline downloads fine,
    // so inspecting it would only produce a false drm_detected refusal.
    if (isYouTubeUrl(tab.url)) {
      discovery = {
        page_url: tab.url,
        page_title: tab.title ?? "video",
        drm_detected: false,
        media_candidates: [],
        caption_candidates: []
      };
      setStatus("YouTube video.", "Captions and comments are fetched by the YouTube pipeline.");
      downloadButton.hidden = false;
      return;
    }

    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: discoverPage
    });
    discovery = mergeDiscoveryResults(results);
    if (!discovery) throw new Error("The page could not be inspected");
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
    // Without this a failed re-inspect leaves the previous page's discovery armed
    // behind a still-visible Download button.
    discovery = undefined;
    downloadButton.hidden = true;
    setStatus("Inspection failed", String(error));
  } finally {
    inspectButton.disabled = false;
  }
}

/** A partitioned cookie shares its name with the unpartitioned one but is distinct. */
function cookieKey(cookie: chrome.cookies.Cookie): string {
  const partition = cookie.partitionKey?.topLevelSite ?? "";
  return `${cookie.storeId}|${partition}|${cookie.domain}|${cookie.path}|${cookie.name}`;
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
      cookies.set(cookieKey(cookie), cookie);
    }
    const partitioned = await chrome.cookies.getAll({
      url,
      partitionKey: { topLevelSite: new URL(discoveryValue.page_url).origin }
    });
    for (const cookie of partitioned) {
      cookies.set(cookieKey(cookie), cookie);
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

// Must not exceed CaptionCandidate.text's max_length in the companion's models.py:
// an oversized body is rejected as a 422 for the entire job, not just that caption.
const MAX_CAPTION_CHARACTERS = 2_000_000;

async function hydrateCaptionBodies(discoveryValue: DiscoveryResult): Promise<void> {
  for (const candidate of discoveryValue.caption_candidates) {
    if (!candidate.url || candidate.text) continue;
    try {
      const response = await fetch(candidate.url, { credentials: "include" });
      if (!response.ok) continue;
      const length = Number(response.headers.get("content-length") || 0);
      if (length > MAX_CAPTION_CHARACTERS) continue;
      const text = await response.text();
      if (text.length <= MAX_CAPTION_CHARACTERS) candidate.text = text;
    } catch {
      // yt-dlp or ElevenLabs remains available when a track cannot be read by JS.
    }
  }
}

const EMPTY_BROWSER_CONTEXT: BrowserContext = { cookies: [], headers: {}, user_agent: "" };

async function startDownload(): Promise<void> {
  if (!discovery) return;
  downloadButton.disabled = true;
  let grantedOrigins: string[] = [];
  try {
    // The YouTube pipeline authenticates nothing and fetches the video itself, so it is
    // sent no cookies at all. Asking for YouTube cookies would mean a new host permission
    // and would hand over the highest-value credential in the profile for no gain; the
    // cost is that age-restricted videos fail, with the pipeline's own message.
    const youtube = isYouTubeUrl(discovery.page_url);
    const origins = youtube ? [] : originPatterns(discovery);
    if (!youtube) {
      const granted = await chrome.permissions.request({ permissions: ["cookies"], origins });
      if (!granted) throw new Error("Site/CDN access was not granted");
      grantedOrigins = origins;
      await hydrateCaptionBodies(discovery);
    }
    const context = youtube ? EMPTY_BROWSER_CONTEXT : await collectCookies(discovery);
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

let capturing = false;

function renderJob(job: VideoJob): void {
  progressElement.value = job.progress;
  const artifacts = [
    job.video_path,
    job.transcript_text_path,
    job.video_storage_key && `R2: ${job.video_storage_key}`
  ];
  setStatus(job.message, artifacts.filter(Boolean).join("\n"));
  // While capturing, the capture buttons are driven by the capture flow, not by the
  // job status, which stays "failed" until the captured request is submitted.
  if (!capturing) captureButton.hidden = !job.can_capture;
  cancelButton.hidden = ["complete", "partial_success", "failed", "cancelled"].includes(job.status);
  if (["complete", "partial_success", "cancelled"].includes(job.status)) stopPolling();
  if (job.status === "failed" && !job.can_capture) {
    // Nothing left to retry, so give the user a way out instead of a dead popup.
    stopPolling();
    inspectButton.hidden = false;
  }
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
  capturing = Boolean(response.capturing);
  inspectButton.hidden = true;
  downloadButton.hidden = true;
  cancelButton.hidden = false;
  // Left to renderJob's can_capture check unless a capture is already running; the
  // companion rejects a capture retry for any job that is not eligible.
  captureButton.hidden = true;
  stopCaptureButton.hidden = !capturing;
  startPolling(response.tracker);
}

inspectButton.addEventListener("click", () => void inspectTab());
downloadButton.addEventListener("click", () => void startDownload());
cancelButton.addEventListener("click", () => {
  void message({ type: "CANCEL_TRACKED_JOB" })
    .then(() => {
      stopPolling();
      setStatus("Cancelled");
      cancelButton.hidden = true;
    })
    .catch((error: unknown) => setStatus("Could not cancel", String(error)));
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
    capturing = true;
    captureButton.hidden = true;
    stopCaptureButton.hidden = false;
    setStatus("Capture active", "Reload or replay the video, then reopen this popup and stop capture.");
  })().catch((error) => setStatus("Could not start capture", String(error)));
});
stopCaptureButton.addEventListener("click", () => {
  stopCaptureButton.disabled = true;
  void message({ type: "STOP_CAPTURE" }).then((response: any) => {
    if (!response.ok) throw new Error(response.error);
    capturing = false;
    stopCaptureButton.hidden = true;
    setStatus("Captured request submitted", `${response.candidates} media request(s) found`);
  }).catch((error) => {
    capturing = false;
    stopCaptureButton.disabled = false;
    setStatus("Capture did not find a video", String(error));
  });
});

void restoreTrackedJob().catch((error: unknown) =>
  setStatus("Could not read the active job", String(error))
);
