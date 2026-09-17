import { createJob, createSession, fetchCurrentUser, getJob, logIn, logOut, signUp } from "./api";
import {
  chooseDirectCandidate,
  discoverPage,
  findVideoGroups,
  isYouTubeUrl,
  mergeDiscoveryResults,
  originPatterns,
  resolveSelectedGroup
} from "./discovery";
import type { FrameDiscoveryResult, VideoGroup } from "./discovery";
import { textureBlock } from "./texture";
import type {
  AuthSession,
  BrowserContext,
  DiscoveryResult,
  ExtensionMessage,
  MediaCandidate,
  StopCaptureResult,
  TrackedJob,
  VideoJob
} from "./types";

const statusElement = document.querySelector<HTMLParagraphElement>("#status")!;
const detailsElement = document.querySelector<HTMLDivElement>("#details")!;
const progressElement = document.querySelector<HTMLProgressElement>("#progress")!;
const videoPickerElement = document.querySelector<HTMLFieldSetElement>("#video-picker")!;
const inspectButton = document.querySelector<HTMLButtonElement>("#inspect")!;
const downloadButton = document.querySelector<HTMLButtonElement>("#download")!;
const verifyButton = document.querySelector<HTMLButtonElement>("#verify")!;
const stopVerifyButton = document.querySelector<HTMLButtonElement>("#stop-verify")!;
const captureButton = document.querySelector<HTMLButtonElement>("#capture")!;
const stopCaptureButton = document.querySelector<HTMLButtonElement>("#stop-capture")!;
const cancelButton = document.querySelector<HTMLButtonElement>("#cancel")!;

const appElement = document.querySelector<HTMLElement>("#app")!;
const authScreenElement = document.querySelector<HTMLElement>("#auth")!;
const authTextureContainer = document.querySelector<HTMLDivElement>("#auth-texture")!;
const authTextureElement = document.querySelector<HTMLPreElement>("#auth-texture-art")!;
const authWelcomeElement = document.querySelector<HTMLDivElement>("#auth-welcome")!;
const authStatusElement = document.querySelector<HTMLParagraphElement>("#auth-status")!;
const authLogoutButton = document.querySelector<HTMLButtonElement>("#auth-logout")!;
const authFormElement = document.querySelector<HTMLFormElement>("#auth-form")!;
const authFormTaglineElement = document.querySelector<HTMLParagraphElement>("#auth-form-tagline")!;
const authEmailInput = document.querySelector<HTMLInputElement>("#auth-email")!;
const authPasswordInput = document.querySelector<HTMLInputElement>("#auth-password")!;
const authDisplayNameInput = document.querySelector<HTMLInputElement>("#auth-display-name")!;
const authErrorElement = document.querySelector<HTMLParagraphElement>("#auth-error")!;
const authSubmitButton = document.querySelector<HTMLButtonElement>("#auth-submit")!;
const authShowLoginButton = document.querySelector<HTMLButtonElement>("#auth-show-login")!;
const authShowSignupButton = document.querySelector<HTMLButtonElement>("#auth-show-signup")!;
const authBackButton = document.querySelector<HTMLButtonElement>("#auth-back")!;

let discovery: DiscoveryResult | undefined;
let activeTabId: number | undefined;
let pollingTimer: number | undefined;

function setStatus(message: string, details = ""): void {
  statusElement.textContent = message;
  detailsElement.textContent = details;
}

const AUTH_STORAGE_KEY = "vidseekAuth";

// The panel is user-resizable (Chrome side panel, not a fixed popup), so the backdrop is
// sized in JS from the container's actual box rather than a fixed column/row count baked
// into the stylesheet — it has to fill whatever width/height Chrome gives it.
let authTextureCharSize: { width: number; height: number } | undefined;

/** Renders one probe character offscreen, in the backdrop's own font, to size a grid cell. */
function measureAuthTextureCharSize(): { width: number; height: number } {
  const probeLength = 20;
  const probe = document.createElement("span");
  probe.textContent = "#".repeat(probeLength);
  probe.style.position = "fixed";
  probe.style.visibility = "hidden";
  probe.style.whiteSpace = "pre";
  const style = getComputedStyle(authTextureElement);
  probe.style.font = style.font;
  probe.style.letterSpacing = style.letterSpacing;
  document.body.appendChild(probe);
  const width = probe.getBoundingClientRect().width / probeLength;
  probe.remove();
  const height = parseFloat(style.lineHeight);
  return { width, height };
}

/** Redraws the backdrop to exactly cover the current size of its container. */
function renderAuthTexture(): void {
  const { width: containerWidth, height: containerHeight } = authTextureContainer.getBoundingClientRect();
  if (containerWidth === 0 || containerHeight === 0) return;
  authTextureCharSize ??= measureAuthTextureCharSize();
  const columns = Math.ceil(containerWidth / authTextureCharSize.width);
  const rows = Math.ceil(containerHeight / authTextureCharSize.height);
  authTextureElement.textContent = textureBlock({ columns, rows });
}

let authSession: AuthSession | undefined;
let authMode: "login" | "signup" = "login";
let authView: "welcome" | "form" = "welcome";

async function readStoredAuth(): Promise<AuthSession | undefined> {
  const stored = await chrome.storage.local.get(AUTH_STORAGE_KEY);
  return stored[AUTH_STORAGE_KEY] as AuthSession | undefined;
}

async function writeStoredAuth(session: AuthSession | undefined): Promise<void> {
  if (session) await chrome.storage.local.set({ [AUTH_STORAGE_KEY]: session });
  else await chrome.storage.local.remove(AUTH_STORAGE_KEY);
}

/** Signed out, the login screen is the whole popup; signed in, it is gone entirely. */
function renderAuth(): void {
  const signedIn = Boolean(authSession);
  authScreenElement.hidden = signedIn;
  appElement.hidden = !signedIn;
  if (!signedIn) renderAuthTexture();
  if (authSession) {
    authStatusElement.textContent = `Signed in as ${authSession.user.display_name || authSession.user.email}`;
    return;
  }
  const onForm = authView === "form";
  authWelcomeElement.hidden = onForm;
  authFormElement.hidden = !onForm;
  authDisplayNameInput.hidden = authMode !== "signup";
  authPasswordInput.autocomplete = authMode === "signup" ? "new-password" : "current-password";
  authSubmitButton.textContent = authMode === "signup" ? "Create account" : "Log in";
  authFormTaglineElement.textContent =
    authMode === "signup" ? "Create an account to get started" : "Log in to your account";
}

function openAuthForm(mode: "login" | "signup"): void {
  authMode = mode;
  authView = "form";
  authErrorElement.textContent = "";
  renderAuth();
  authEmailInput.focus();
}

async function handleAuthSubmit(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  authErrorElement.textContent = "";
  authSubmitButton.disabled = true;
  try {
    const email = authEmailInput.value.trim();
    const password = authPasswordInput.value;
    const session =
      authMode === "signup"
        ? await signUp(email, password, authDisplayNameInput.value.trim())
        : await logIn(email, password);
    authSession = session;
    await writeStoredAuth(session);
    authFormElement.reset();
    renderAuth();
  } catch (error) {
    authErrorElement.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    authSubmitButton.disabled = false;
  }
}

async function handleAuthLogout(): Promise<void> {
  authLogoutButton.disabled = true;
  try {
    if (authSession) await logOut(authSession.token).catch(() => undefined);
  } finally {
    authSession = undefined;
    authView = "welcome";
    await writeStoredAuth(undefined);
    renderAuth();
    authLogoutButton.disabled = false;
  }
}

/**
 * A stored token can outlive the companion process: it is verified in memory only
 * (backend/core/auth.py), so a restart drops every signed-in session. Rather than show a
 * stale "signed in" state that fails the moment it is used, this re-checks the token against
 * `/v1/auth/me` on every popup open and quietly returns to the login screen if it no longer
 * verifies.
 */
async function restoreAuthState(): Promise<void> {
  const stored = await readStoredAuth();
  if (!stored) {
    renderAuth();
    return;
  }
  authSession = stored;
  renderAuth();
  try {
    const user = await fetchCurrentUser(stored.token);
    authSession = { token: stored.token, user };
    await writeStoredAuth(authSession);
  } catch {
    authSession = undefined;
    await writeStoredAuth(undefined);
  }
  renderAuth();
}

function message<T = Record<string, unknown>>(payload: ExtensionMessage): Promise<T> {
  return chrome.runtime.sendMessage(payload) as Promise<T>;
}

function resetVideoPicker(): void {
  videoPickerElement.hidden = true;
  videoPickerElement.replaceChildren();
}

/** Stopped, notified state for any DRM signal, whether seen at inspect time or after playback. */
function reportDrmBlocked(reason: string): void {
  discovery = undefined;
  downloadButton.hidden = true;
  verifyButton.hidden = true;
  stopVerifyButton.hidden = true;
  captureButton.hidden = true;
  cancelButton.hidden = true;
  void clearVerifyState();
  void chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
  void chrome.action.setBadgeText({ text: "DRM" });
  setStatus("DRM detected — download stopped", reason);
}

/**
 * Adaptive/MSE players are exactly the ones that can switch to a DRM-protected rendition
 * only once playback actually starts (open_tasks.md #2c): a plain progressive `<video src>`
 * cannot. Gating only these behind a play-and-verify step keeps a simple direct file fast.
 */
function needsPlaybackVerification(discoveryValue: DiscoveryResult): boolean {
  return (
    discoveryValue.media_candidates.length === 0 ||
    discoveryValue.media_candidates.some((candidate) => candidate.kind === "hls" || candidate.kind === "dash")
  );
}

/**
 * Applies the DRM/playback-verification gate to a discovery result and sets the popup's
 * button state accordingly. Shared by the single-video path and the video picker below, so
 * picking a specific video from several never skips the same DRM check a single video gets.
 */
function presentDiscovery(discoveryValue: DiscoveryResult): void {
  discovery = discoveryValue;
  if (discoveryValue.drm_detected) {
    reportDrmBlocked("This player reports DRM protection (video.mediaKeys is already set).");
    return;
  }
  if (needsPlaybackVerification(discoveryValue)) {
    downloadButton.hidden = true;
    verifyButton.hidden = false;
    setStatus(
      discoveryValue.media_candidates.length ? "Adaptive player detected." : "No direct source found yet.",
      "DRM can only be confirmed once playback starts. Click 'Verify & play', then press Play in the page."
    );
  } else {
    verifyButton.hidden = true;
    downloadButton.hidden = false;
    setStatus(
      "Video discovered.",
      `${discoveryValue.media_candidates.length} media source(s), ${discoveryValue.caption_candidates.length} caption/transcript source(s)`
    );
  }
}

/** Lets the user pick which of several videos found on the page to download. */
function renderVideoPicker(groups: VideoGroup[], frames: FrameDiscoveryResult[]): void {
  const legend = document.createElement("legend");
  legend.textContent = "Choose a video";
  videoPickerElement.replaceChildren(legend);

  for (const [index, group] of groups.entries()) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "video-group";
    input.value = String(index);
    input.addEventListener("change", () => presentDiscovery(resolveSelectedGroup(group, frames)));
    label.append(input, ` ${group.label}`);
    videoPickerElement.appendChild(label);
  }

  videoPickerElement.hidden = false;
  setStatus(`Found ${groups.length} videos on this page.`, "Choose which one to download below.");
}

async function inspectTab(): Promise<void> {
  inspectButton.disabled = true;
  discovery = undefined;
  downloadButton.hidden = true;
  resetVideoPicker();
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
      verifyButton.hidden = true;
      downloadButton.hidden = false;
      return;
    }

    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: discoverPage
    });

    // More than one frame found a video: let the user pick instead of silently combining or
    // arbitrarily preferring one, which is what the single merged DiscoveryResult below would
    // otherwise do.
    const groups = findVideoGroups(results, tab.title ?? "");
    if (groups) {
      renderVideoPicker(groups, results);
      return;
    }

    const merged = mergeDiscoveryResults(results);
    if (!merged) throw new Error("The page could not be inspected");
    presentDiscovery(merged);
  } catch (error) {
    // Without this a failed re-inspect leaves the previous page's discovery armed
    // behind a still-visible Download button.
    discovery = undefined;
    downloadButton.hidden = true;
    verifyButton.hidden = true;
    resetVideoPicker();
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

/** Requests the site/CDN origins a discovery result touches; YouTube needs none of them. */
async function grantSiteAccess(discoveryValue: DiscoveryResult): Promise<string[]> {
  if (isYouTubeUrl(discoveryValue.page_url)) return [];
  const origins = originPatterns(discoveryValue);
  const granted = await chrome.permissions.request({ permissions: ["cookies"], origins });
  if (!granted) throw new Error("Site/CDN access was not granted");
  return origins;
}

async function startDownload(): Promise<void> {
  if (!discovery || !authSession) return;
  downloadButton.disabled = true;
  let grantedOrigins: string[] = [];
  try {
    // The YouTube pipeline authenticates nothing and fetches the video itself, so it is
    // sent no cookies at all. Asking for YouTube cookies would mean a new host permission
    // and would hand over the highest-value credential in the profile for no gain; the
    // cost is that age-restricted videos fail, with the pipeline's own message.
    const youtube = isYouTubeUrl(discovery.page_url);
    grantedOrigins = await grantSiteAccess(discovery);
    if (!youtube) await hydrateCaptionBodies(discovery);
    const context = youtube ? EMPTY_BROWSER_CONTEXT : await collectCookies(discovery);
    const token = await createSession();
    const job = await createJob(token, authSession.token, discovery, context);
    const tracker: TrackedJob = { jobId: job.job_id, token, grantedOrigins };
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
    verifyButton.hidden = true;
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

/** Merges media candidates confirmed during playback ahead of what discovery first saw. */
function mergeCandidates(primary: MediaCandidate[], fallback: MediaCandidate[]): MediaCandidate[] {
  const seen = new Set(primary.map((candidate) => candidate.url));
  return [...primary, ...fallback.filter((candidate) => !seen.has(candidate.url))];
}

interface VerifyState {
  discovery: DiscoveryResult;
  grantedOrigins: string[];
}

const VERIFY_STATE_KEY = "vidseekVerifyState";

// The popup closes the moment the user clicks into the page to press Play, so the discovery
// result and the origins granted for it must survive that close/reopen in session storage —
// a module-level variable would not.
async function saveVerifyState(state: VerifyState): Promise<void> {
  await chrome.storage.session.set({ [VERIFY_STATE_KEY]: state });
}

async function readVerifyState(): Promise<VerifyState | undefined> {
  const stored = await chrome.storage.session.get(VERIFY_STATE_KEY);
  return stored[VERIFY_STATE_KEY] as VerifyState | undefined;
}

async function clearVerifyState(): Promise<void> {
  await chrome.storage.session.remove(VERIFY_STATE_KEY);
}

async function startVerification(): Promise<void> {
  if (!discovery || activeTabId === undefined) return;
  verifyButton.disabled = true;
  let grantedOrigins: string[] = [];
  try {
    grantedOrigins = await grantSiteAccess(discovery);
    await message({ type: "START_CAPTURE", tabId: activeTabId });
    await saveVerifyState({ discovery, grantedOrigins });
    verifyButton.hidden = true;
    downloadButton.hidden = true;
    stopVerifyButton.hidden = false;
    cancelButton.hidden = false;
    setStatus(
      "Verification active.",
      "Reload the page and press Play, then reopen this popup and click 'Finish verification'."
    );
  } catch (error) {
    if (grantedOrigins.length) {
      await chrome.permissions.remove({ origins: grantedOrigins }).catch(() => false);
      await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
    }
    setStatus("Could not start verification", String(error));
  } finally {
    verifyButton.disabled = false;
  }
}

type StopCaptureResponse = ({ ok: true } & StopCaptureResult) | { ok: false; error: string };

async function finishVerification(): Promise<void> {
  stopVerifyButton.disabled = true;
  try {
    const verifyState = await readVerifyState();
    const response = await message<StopCaptureResponse>({ type: "STOP_CAPTURE" });
    if (!response.ok) throw new Error(response.error);
    await clearVerifyState();
    stopVerifyButton.hidden = true;
    cancelButton.hidden = true;
    if (response.drm_detected) {
      if (verifyState?.grantedOrigins.length) {
        await chrome.permissions.remove({ origins: verifyState.grantedOrigins }).catch(() => false);
        await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
      }
      reportDrmBlocked(response.reason ?? "DRM was detected during playback.");
      return;
    }
    if (!verifyState) throw new Error("Lost discovery state; inspect the page again");
    discovery = {
      ...verifyState.discovery,
      media_candidates: mergeCandidates(response.candidates, verifyState.discovery.media_candidates)
    };
    setStatus(
      "No DRM detected.",
      `${response.candidates.length} media request(s) confirmed during playback. Starting download...`
    );
    await startDownload();
  } catch (error) {
    // The capture already detached on the background side (win or lose), so there is
    // nothing left to finish — send the user back to a fresh inspect rather than leaving
    // a "Finish verification" button that would now do nothing.
    await clearVerifyState().catch(() => undefined);
    stopVerifyButton.hidden = true;
    cancelButton.hidden = true;
    inspectButton.hidden = false;
    setStatus("Verification did not find a video", String(error));
  } finally {
    stopVerifyButton.disabled = false;
  }
}

let capturing = false;

function renderJob(job: VideoJob): void {
  progressElement.value = job.progress;
  const artifacts = [
    job.video_path,
    job.transcript_text_path,
    job.video_storage_key && `Stored: ${job.video_storage_key}`
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
  const response = await message<{ ok: boolean; tracker?: TrackedJob; capturing?: boolean; verifying?: boolean }>({
    type: "GET_TRACKED_JOB"
  });
  if (response.verifying) {
    inspectButton.hidden = true;
    downloadButton.hidden = true;
    verifyButton.hidden = true;
    stopVerifyButton.hidden = false;
    cancelButton.hidden = false;
    setStatus(
      "Verification active.",
      "Reopen this popup after pressing Play in the page, then click 'Finish verification'."
    );
    return;
  }
  if (!response.tracker) return;
  capturing = Boolean(response.capturing);
  inspectButton.hidden = true;
  downloadButton.hidden = true;
  verifyButton.hidden = true;
  cancelButton.hidden = false;
  // Left to renderJob's can_capture check unless a capture is already running; the
  // companion rejects a capture retry for any job that is not eligible.
  captureButton.hidden = true;
  stopCaptureButton.hidden = !capturing;
  startPolling(response.tracker);
}

inspectButton.addEventListener("click", () => void inspectTab());
downloadButton.addEventListener("click", () => void startDownload());
verifyButton.addEventListener("click", () => void startVerification());
stopVerifyButton.addEventListener("click", () => void finishVerification());
cancelButton.addEventListener("click", () => {
  void (async () => {
    const verifyState = await readVerifyState();
    await message({ type: "CANCEL_TRACKED_JOB" });
    stopPolling();
    if (verifyState?.grantedOrigins.length) {
      await chrome.permissions.remove({ origins: verifyState.grantedOrigins }).catch(() => false);
      await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
    }
    await clearVerifyState();
    setStatus("Cancelled");
    cancelButton.hidden = true;
    stopVerifyButton.hidden = true;
    inspectButton.hidden = false;
  })().catch((error: unknown) => setStatus("Could not cancel", String(error)));
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
  void message<StopCaptureResponse>({ type: "STOP_CAPTURE" })
    .then((response) => {
      if (!response.ok) throw new Error(response.error);
      capturing = false;
      stopCaptureButton.hidden = true;
      if (response.drm_detected) {
        reportDrmBlocked(response.reason ?? "DRM was detected during playback.");
        return;
      }
      setStatus("Captured request submitted", `${response.candidates.length} media request(s) found`);
    })
    .catch((error: unknown) => {
      capturing = false;
      stopCaptureButton.disabled = false;
      setStatus("Capture did not find a video", String(error));
    });
});

void restoreTrackedJob().catch((error: unknown) =>
  setStatus("Could not read the active job", String(error))
);

authShowLoginButton.addEventListener("click", () => openAuthForm("login"));
authShowSignupButton.addEventListener("click", () => openAuthForm("signup"));
authBackButton.addEventListener("click", () => {
  authView = "welcome";
  authErrorElement.textContent = "";
  authFormElement.reset();
  renderAuth();
});
authFormElement.addEventListener("submit", (event) => void handleAuthSubmit(event));
authLogoutButton.addEventListener("click", () => void handleAuthLogout());

// Chrome lets the side panel be resized while it's open, so the backdrop is redrawn
// whenever the panel's own box changes rather than only once at load.
let authTextureResizeFrame: number | undefined;
new ResizeObserver(() => {
  if (authScreenElement.hidden) return;
  if (authTextureResizeFrame !== undefined) cancelAnimationFrame(authTextureResizeFrame);
  authTextureResizeFrame = requestAnimationFrame(renderAuthTexture);
}).observe(authScreenElement);

void restoreAuthState();
