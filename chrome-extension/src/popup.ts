// Coordinate sign-in, inspection, playback verification, scans, and the chat that follows.
import { hydrateCaptionBodies } from "./caption-fetch";
import { closeChat, openChat } from "./chat";
import { inspectFrames } from "./frame-discovery";
import {
  cancelJob,
  createJob,
  createSession,
  fetchCurrentUser,
  getJob,
  getVideo,
  logIn,
  logOut,
  signUp,
} from "./api";
import {
  chooseDirectCandidate,
  describeCapturedSources,
  findVideoGroups,
  isYouTubeUrl,
  mergeDiscoveryResults,
  originPatterns,
  pageOriginPatterns,
  resolveSelectedGroup,
} from "./discovery";
import type { FrameDiscoveryResult, VideoGroup } from "./discovery";
import {
  clearScannedVideo,
  readScannedVideo,
  recordScannedVideoId,
  writeScannedVideo,
} from "./scanned-video";
import { textureBlock } from "./texture";
import { allowsChat } from "./types";
import type {
  AuthSession,
  BrowserContext,
  DiscoveryResult,
  ExtensionMessage,
  MediaCandidate,
  ScannedVideo,
  StopCaptureResult,
  TrackedJob,
  VideoJob,
} from "./types";

const statusElement = document.querySelector<HTMLParagraphElement>("#status")!;
const detailsElement = document.querySelector<HTMLDivElement>("#details")!;
const progressElement =
  document.querySelector<HTMLProgressElement>("#progress")!;
const videoPickerElement =
  document.querySelector<HTMLFieldSetElement>("#video-picker")!;
const inspectButton = document.querySelector<HTMLButtonElement>("#inspect")!;
const downloadButton = document.querySelector<HTMLButtonElement>("#download")!;
const verifyButton = document.querySelector<HTMLButtonElement>("#verify")!;
const stopVerifyButton =
  document.querySelector<HTMLButtonElement>("#stop-verify")!;
const captureButton = document.querySelector<HTMLButtonElement>("#capture")!;
const stopCaptureButton =
  document.querySelector<HTMLButtonElement>("#stop-capture")!;
const cancelButton = document.querySelector<HTMLButtonElement>("#cancel")!;
const cancelVerifyButton =
  document.querySelector<HTMLButtonElement>("#cancel-verify")!;
const scanAnotherButton =
  document.querySelector<HTMLButtonElement>("#scan-another")!;
const chatScanAnotherButton =
  document.querySelector<HTMLButtonElement>("#chat-scan-another")!;
const actionHintElement =
  document.querySelector<HTMLParagraphElement>("#action-hint")!;
const checkStepsElement =
  document.querySelector<HTMLOListElement>("#check-steps")!;

const inspectViewElement = document.querySelector<HTMLElement>("#inspect-view")!;
const processingViewElement =
  document.querySelector<HTMLElement>("#processing-view")!;
const chatViewElement = document.querySelector<HTMLElement>("#chat-view")!;
const processingHeadingElement =
  document.querySelector<HTMLHeadingElement>("#processing-heading")!;
const processingTitleElement =
  document.querySelector<HTMLParagraphElement>("#processing-title")!;
const processingStatusElement =
  document.querySelector<HTMLParagraphElement>("#processing-status")!;
const processingDetailsElement =
  document.querySelector<HTMLDivElement>("#processing-details")!;
const processingNoteElement =
  document.querySelector<HTMLParagraphElement>("#processing-note")!;
const scanLoaderElement = document.querySelector<HTMLDivElement>("#scan-loader")!;
const scanStepElements = [
  ...document.querySelectorAll<HTMLLIElement>("#scan-steps li"),
];

const appElement = document.querySelector<HTMLElement>("#app")!;
const appTextureContainer =
  document.querySelector<HTMLDivElement>("#app-texture")!;
const authScreenElement = document.querySelector<HTMLElement>("#auth")!;
const authTextureContainer =
  document.querySelector<HTMLDivElement>("#auth-texture")!;
const authWelcomeElement =
  document.querySelector<HTMLDivElement>("#auth-welcome")!;
const authStatusElement =
  document.querySelector<HTMLParagraphElement>("#auth-status")!;
const authLogoutButton =
  document.querySelector<HTMLButtonElement>("#auth-logout")!;
const authFormElement = document.querySelector<HTMLFormElement>("#auth-form")!;
const authFormTaglineElement =
  document.querySelector<HTMLParagraphElement>("#auth-form-tagline")!;
const authEmailInput = document.querySelector<HTMLInputElement>("#auth-email")!;
const authPasswordInput =
  document.querySelector<HTMLInputElement>("#auth-password")!;
const authDisplayNameInput =
  document.querySelector<HTMLInputElement>("#auth-display-name")!;
const authErrorElement =
  document.querySelector<HTMLParagraphElement>("#auth-error")!;
const authSubmitButton =
  document.querySelector<HTMLButtonElement>("#auth-submit")!;
const authShowLoginButton =
  document.querySelector<HTMLButtonElement>("#auth-show-login")!;
const authShowSignupButton =
  document.querySelector<HTMLButtonElement>("#auth-show-signup")!;
const authBackButton = document.querySelector<HTMLButtonElement>("#auth-back")!;

let discovery: DiscoveryResult | undefined;
let activeTabId: number | undefined;
let pollingTimer: number | undefined;

/** The three screens a signed-in user moves through: find a video, wait for it, chat. */
type AppView = "inspect" | "processing" | "chat";
let currentView: AppView | undefined;

function showView(view: AppView | undefined): void {
  if (currentView === "chat" && view !== "chat") closeChat();
  currentView = view;
  inspectViewElement.hidden = view !== "inspect";
  processingViewElement.hidden = view !== "processing";
  chatViewElement.hidden = view !== "chat";
  appElement.dataset.view = view ?? "";
  if (view && view !== "chat") renderTexture(appTextureContainer);
}

/** Writes to the status block of whichever screen is showing. */
function setStatus(message: string, details = ""): void {
  const processing = currentView === "processing";
  (processing ? processingStatusElement : statusElement).textContent = message;
  (processing ? processingDetailsElement : detailsElement).textContent = details;
}

const AUTH_STORAGE_KEY = "vidseekAuth";

// The panel is user-resizable (Chrome side panel, not a fixed popup), so the backdrop is
// sized in JS from the container's actual box rather than a fixed column/row count baked
// into the stylesheet — it has to fill whatever width/height Chrome gives it. The sign-in
// screen and the signed-in app draw the same field, in the same font, behind their content.
let textureCharSize: { width: number; height: number } | undefined;

/** Renders one probe character offscreen, in the backdrop's own font, to size a grid cell. */
function measureTextureCharSize(art: HTMLPreElement): {
  width: number;
  height: number;
} {
  const probeLength = 20;
  const probe = document.createElement("span");
  probe.textContent = "#".repeat(probeLength);
  probe.style.position = "fixed";
  probe.style.visibility = "hidden";
  probe.style.whiteSpace = "pre";
  const style = getComputedStyle(art);
  probe.style.font = style.font;
  probe.style.letterSpacing = style.letterSpacing;
  document.body.appendChild(probe);
  const width = probe.getBoundingClientRect().width / probeLength;
  probe.remove();
  const height = parseFloat(style.lineHeight);
  return { width, height };
}

/** Redraws a backdrop to exactly cover the current size of its container. */
function renderTexture(container: HTMLElement): void {
  const art = container.querySelector("pre")!;
  const { width: containerWidth, height: containerHeight } =
    container.getBoundingClientRect();
  if (containerWidth === 0 || containerHeight === 0) return;
  textureCharSize ??= measureTextureCharSize(art);
  const columns = Math.ceil(containerWidth / textureCharSize.width);
  const rows = Math.ceil(containerHeight / textureCharSize.height);
  art.textContent = textureBlock({ columns, rows });
}

let authSession: AuthSession | undefined;
let authMode: "login" | "signup" = "login";
let authView: "welcome" | "form" = "welcome";

async function readStoredAuth(): Promise<AuthSession | undefined> {
  const stored = await chrome.storage.local.get(AUTH_STORAGE_KEY);
  return stored[AUTH_STORAGE_KEY] as AuthSession | undefined;
}

async function writeStoredAuth(
  session: AuthSession | undefined,
): Promise<void> {
  if (session) await chrome.storage.local.set({ [AUTH_STORAGE_KEY]: session });
  else await chrome.storage.local.remove(AUTH_STORAGE_KEY);
}

/** Signed out, the login screen is the whole popup; signed in, it is gone entirely. */
function renderAuth(): void {
  const signedIn = Boolean(authSession);
  authScreenElement.hidden = signedIn;
  appElement.hidden = !signedIn;
  if (!signedIn) renderTexture(authTextureContainer);
  if (authSession) {
    const name = authSession.user.display_name || authSession.user.email;
    authStatusElement.textContent = name;
    authStatusElement.title = `Signed in as ${name}`;
    return;
  }
  const onForm = authView === "form";
  authWelcomeElement.hidden = onForm;
  authFormElement.hidden = !onForm;
  authDisplayNameInput.hidden = authMode !== "signup";
  authPasswordInput.autocomplete =
    authMode === "signup" ? "new-password" : "current-password";
  authSubmitButton.textContent =
    authMode === "signup" ? "Create account" : "Log in";
  authFormTaglineElement.textContent =
    authMode === "signup"
      ? "Create an account to get started"
      : "Log in to your account";
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
    void enterSignedInApp();
  } catch (error) {
    authErrorElement.textContent =
      error instanceof Error ? error.message : String(error);
  } finally {
    authSubmitButton.disabled = false;
  }
}

/**
 * Signing out only lets go of this panel's view of the scan. The job keeps running in the
 * companion, the background worker keeps tracking it, and the scan stays recorded under
 * this user, so signing back in returns to the processing screen or straight to the chat.
 */
async function handleAuthLogout(): Promise<void> {
  authLogoutButton.disabled = true;
  stopPolling();
  showView(undefined);
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
  if (authSession) await enterSignedInApp();
}

/** Opens whichever screen the signed-in user left off on. */
async function enterSignedInApp(): Promise<void> {
  await restoreSignedInView().catch((error: unknown) => {
    showView("inspect");
    setStatus("Could not read the active scan", String(error));
  });
}

function message<T = Record<string, unknown>>(
  payload: ExtensionMessage,
): Promise<T> {
  return chrome.runtime.sendMessage(payload) as Promise<T>;
}

function resetVideoPicker(): void {
  videoPickerElement.hidden = true;
  videoPickerElement.replaceChildren();
}

/**
 * What the inspect screen is asking the user to do next. Each step shows only its own
 * buttons, with one line under the main one saying what pressing it will do:
 * - find: nothing found yet, so looking is the only thing to do;
 * - scan: a video is ready to send to the scan;
 * - check: an adaptive player has to be watched playing once before it can be scanned;
 * - checking: that playback check is running, waiting for the user to play the video.
 */
type InspectStep = "find" | "scan" | "check" | "checking";

const ACTION_HINTS: Record<InspectStep, string> = {
  find: "",
  scan: "Chrome asks you to let VidSeek read this site, then the scan starts.",
  check:
    "Chrome asks you to let VidSeek read this site, then shows a “started debugging this browser” bar while the check runs. That bar is VidSeek watching the video load, and it goes away when the check ends.",
  checking: "VidSeek then looks at what loaded and starts the scan.",
};

function showInspectStep(step: InspectStep, hint = ACTION_HINTS[step]): void {
  downloadButton.hidden = step !== "scan";
  verifyButton.hidden = step !== "check";
  stopVerifyButton.hidden = step !== "checking";
  cancelVerifyButton.hidden = step !== "checking";
  // Once there is a next step, looking again is the fallback, not the thing to do.
  inspectButton.hidden = step === "checking";
  inspectButton.textContent = step === "find" ? "Find video" : "Search again";
  inspectButton.classList.toggle("pill--dark", step === "find");
  inspectButton.classList.toggle("pill--light", step !== "find");
  checkStepsElement.hidden = step !== "check" && step !== "checking";
  checkStepsElement.dataset.progress = step === "checking" ? "playing" : "";
  actionHintElement.textContent = hint;
}

/** Stopped, notified state for any DRM signal, whether seen at inspect time or after playback. */
function reportDrmBlocked(reason: string): void {
  discovery = undefined;
  showInspectStep("find");
  captureButton.hidden = true;
  cancelButton.hidden = true;
  void clearVerifyState();
  void chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
  void chrome.action.setBadgeText({ text: "DRM" });
  // A capture retry runs on the processing screen, and its job is already cancelled.
  if (currentView === "processing") showScanEnded("DRM detected", reason);
  else setStatus("DRM detected — scan stopped", reason);
}

/**
 * Adaptive/MSE players are exactly the ones that can switch to a DRM-protected rendition
 * only once playback actually starts: a plain progressive `<video src>`
 * cannot. Gating only these behind a play-and-verify step keeps a simple direct file fast.
 */
function needsPlaybackVerification(discoveryValue: DiscoveryResult): boolean {
  if (isYouTubeUrl(discoveryValue.page_url)) return false;
  return (
    discoveryValue.media_candidates.length === 0 ||
    discoveryValue.media_candidates.some(
      (candidate) => candidate.kind === "hls" || candidate.kind === "dash",
    )
  );
}

/**
 * Applies the DRM/playback-verification gate to a discovery result and sets the popup's
 * button state accordingly. Shared by the single-video path and the video picker below, so
 * picking a specific video from several never skips the same DRM check a single video gets.
 *
 * `playbackVerified` marks a result that came out of a finished playback check: it was
 * already watched playing without DRM, so asking for the check again would only send the
 * user round the same loop.
 */
function presentDiscovery(
  discoveryValue: DiscoveryResult,
  playbackVerified = false,
): void {
  discovery = discoveryValue;
  if (discoveryValue.drm_detected) {
    reportDrmBlocked(
      "This player reports DRM protection (video.mediaKeys is already set).",
    );
    return;
  }
  if (playbackVerified) {
    showInspectStep("scan");
    setStatus(
      "Ready to scan.",
      "The playback check passed: this video isn't copy-protected.",
    );
  } else if (needsPlaybackVerification(discoveryValue)) {
    showInspectStep("check");
    setStatus(
      "One more step: a quick playback check.",
      discoveryValue.media_candidates.length
        ? "This site streams its video in pieces. VidSeek has to see it play once to find the full video and make sure it isn't copy-protected (DRM)."
        : "No video file was found yet. Some players only load one once the video plays, so VidSeek has to watch it play once to find it and make sure it isn't copy-protected (DRM).",
    );
  } else {
    showInspectStep("scan");
    const captions = discoveryValue.caption_candidates.length;
    setStatus(
      "Video found.",
      captions
        ? `Captions found too (${captions}), so the transcript will be quick.`
        : "",
    );
  }
}

/** Lets the user pick which of several videos found on the page to download. */
function renderVideoPicker(
  groups: VideoGroup[],
  frames: FrameDiscoveryResult[],
  playbackVerified = false,
): void {
  const legend = document.createElement("legend");
  legend.textContent = "Choose a video";
  videoPickerElement.replaceChildren(legend);

  const inputs = groups.map((group, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "video-group";
    input.value = String(index);
    input.addEventListener("change", () =>
      presentDiscovery(resolveSelectedGroup(group, frames), playbackVerified),
    );
    const text = document.createElement("span");
    text.className = "video-choice";
    const title = document.createElement("span");
    title.className = "video-choice__label";
    title.textContent = group.label;
    text.append(title);
    if (group.detail) {
      const detail = document.createElement("span");
      detail.className = "video-choice__detail";
      detail.textContent = group.detail;
      text.append(detail);
    }
    label.append(input, text);
    videoPickerElement.appendChild(label);
    return input;
  });

  videoPickerElement.hidden = false;
  // One choice is always picked for the user, so there is always a next step to take: the
  // one most likely to be what they are watching, or else the first.
  const recommendedIndex = groups.findIndex((group) => group.recommended);
  const preselected = Math.max(recommendedIndex, 0);
  inputs[preselected]!.checked = true;
  presentDiscovery(
    resolveSelectedGroup(groups[preselected]!, frames),
    playbackVerified,
  );
  // A DRM refusal for that choice keeps its own message; another choice may be clean.
  if (!discovery) return;
  setStatus(
    `Found ${groups.length} videos on this page.`,
    recommendedIndex >= 0
      ? "The one you're most likely watching is picked. Check the notes under each video, and choose another if it's the wrong one."
      : "The first one is picked. Check the notes under each video, and choose another if it's the wrong one.",
  );
}

async function inspectTab(): Promise<void> {
  inspectButton.disabled = true;
  discovery = undefined;
  showInspectStep("find");
  resetVideoPicker();
  setStatus("Looking for a video on this tab…");
  try {
    const [tab] = await chrome.tabs.query({
      active: true,
      currentWindow: true,
    });
    if (!tab?.id || !tab.url?.startsWith("http"))
      throw new Error("Open an HTTP or HTTPS video page first");
    activeTabId = tab.id;

    // Decided from the tab's own URL, before any script runs in the page. Discovery would
    // find nothing usable on YouTube anyway — its media URLs are expiring googlevideo
    // links — and the YouTube player reports DRM on streams the pipeline downloads fine,
    // so inspecting it would only produce a false drm_detected refusal.
    if (isYouTubeUrl(tab.url)) {
      discovery = {
        page_url: tab.url,
        page_title: tab.title || "video",
        drm_detected: false,
        media_candidates: [],
        caption_candidates: [],
      };
      setStatus(
        "YouTube video found.",
        "Captions and comments are fetched by the YouTube pipeline.",
      );
      // YouTube is scanned without any site access, so there is no Chrome prompt to warn of.
      showInspectStep("scan", "");
      return;
    }

    const results = await inspectFrames(tab.id, true);

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
    showInspectStep("find");
    resetVideoPicker();
    setStatus("Couldn't look for a video on this tab", String(error));
  } finally {
    inspectButton.disabled = false;
  }
}

/** A partitioned cookie shares its name with the unpartitioned one but is distinct. */
function cookieKey(cookie: chrome.cookies.Cookie): string {
  const partition = cookie.partitionKey?.topLevelSite ?? "";
  return `${cookie.storeId}|${partition}|${cookie.domain}|${cookie.path}|${cookie.name}`;
}

async function collectCookies(
  discoveryValue: DiscoveryResult,
): Promise<BrowserContext> {
  const cookies = new Map<string, chrome.cookies.Cookie>();
  const urls = [
    discoveryValue.frame_url || discoveryValue.page_url,
    discoveryValue.page_url,
    ...discoveryValue.media_candidates.map((candidate) => candidate.url),
    ...discoveryValue.caption_candidates.flatMap((candidate) =>
      candidate.url ? [candidate.url] : [],
    ),
  ];
  for (const url of urls) {
    if (!url.startsWith("http")) continue;
    for (const cookie of await chrome.cookies.getAll({ url })) {
      cookies.set(cookieKey(cookie), cookie);
    }
    const partitioned = await chrome.cookies.getAll({
      url,
      partitionKey: { topLevelSite: new URL(discoveryValue.page_url).origin },
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
      expiration_date: cookie.expirationDate,
    })),
    headers: {
      Referer: discoveryValue.frame_url || discoveryValue.page_url,
      Origin: new URL(discoveryValue.frame_url || discoveryValue.page_url)
        .origin,
    },
    user_agent: navigator.userAgent,
  };
}

const EMPTY_BROWSER_CONTEXT: BrowserContext = {
  cookies: [],
  headers: {},
  user_agent: "",
};

/**
 * Requests the site/CDN origins a discovery result touches; YouTube needs none of them.
 *
 * Only the page's own site is required. A CDN or caption host adds its cookies and caption
 * bodies when Chrome allows it, and the scan goes ahead without them when it does not. That
 * is what happens after a playback check: the check was already allowed the page, and the
 * stream it found usually lives on a CDN host (hls.ted.com for www.ted.com) that the scan's
 * prompt then asks for on its own. Refusing that host must not stop the scan.
 */
async function grantSiteAccess(
  discoveryValue: DiscoveryResult,
): Promise<string[]> {
  if (
    isYouTubeUrl(discoveryValue.page_url) &&
    !discoveryValue.caption_candidates.some((c) => c.url)
  )
    return [];
  const youtube = isYouTubeUrl(discoveryValue.page_url);
  const origins = originPatterns(discoveryValue).filter(
    (origin) => !youtube || !isYouTubeUrl(origin),
  );
  const permissions = youtube ? [] : ["cookies"];
  const existing = await chrome.permissions.getAll();
  const granted = await chrome.permissions.request({ permissions, origins });
  if (granted)
    return origins.filter((origin) => !existing.origins?.includes(origin));
  // Chrome grants a request whole or not at all, so nothing new was granted here.
  const requiredOrigins = pageOriginPatterns(discoveryValue).filter((origin) =>
    origins.includes(origin),
  );
  const hasRequired = await chrome.permissions.contains({
    permissions,
    origins: requiredOrigins,
  });
  if (!hasRequired) {
    const hosts = requiredOrigins.map((origin) => new URL(origin).hostname);
    throw new Error(
      `Chrome didn't allow VidSeek to read ${hosts.join(", ")}. Press the button again and choose Allow in Chrome's prompt.`,
    );
  }
  return [];
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
    await hydrateCaptionBodies(discovery, activeTabId);
    const context = youtube
      ? EMPTY_BROWSER_CONTEXT
      : await collectCookies(discovery);
    const token = await createSession();
    const job = await createJob(token, authSession.token, discovery, context);
    const tracker: TrackedJob = { jobId: job.job_id, token, grantedOrigins };
    const direct = chooseDirectCandidate(discovery.media_candidates);
    if (job.acquisition_mode === "browser_download" && direct) {
      await message({
        type: "START_BROWSER_DOWNLOAD",
        tracker,
        url: direct.url,
        filename: discovery.page_title,
      });
    } else {
      await message({ type: "TRACK_JOB", tracker });
    }
    const scan: ScannedVideo = {
      userId: authSession.user.id,
      jobId: job.job_id,
      jobToken: token,
      title: discovery.page_title,
      pageUrl: discovery.page_url,
      videoId: job.video_id,
    };
    await writeScannedVideo(scan);
    showInspectStep("find");
    resetVideoPicker();
    showScanInProgress(scan);
    renderJob(job);
    // A video already in the system finishes its job at once, and renderJob has settled it.
    if (!isScanFinished(job)) startPolling(tracker);
  } catch (error) {
    if (grantedOrigins.length) {
      await chrome.permissions
        .remove({ origins: grantedOrigins })
        .catch(() => false);
      await chrome.permissions
        .remove({ permissions: ["cookies"] })
        .catch(() => false);
    }
    setStatus("Could not start the scan", String(error));
  } finally {
    downloadButton.disabled = false;
  }
}

/** Merges media candidates confirmed during playback ahead of what discovery first saw. */
function mergeCandidates(
  primary: MediaCandidate[],
  fallback: MediaCandidate[],
): MediaCandidate[] {
  const seen = new Set(primary.map((candidate) => candidate.url));
  return [
    ...primary,
    ...fallback.filter((candidate) => !seen.has(candidate.url)),
  ];
}

interface VerifyState {
  discovery: DiscoveryResult;
  grantedOrigins: string[];
  tabId: number;
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
    await saveVerifyState({ discovery, grantedOrigins, tabId: activeTabId });
    showInspectStep("checking");
    setStatus("Playback check running.", "Now play the video in the page.");
  } catch (error) {
    if (grantedOrigins.length) {
      await chrome.permissions
        .remove({ origins: grantedOrigins })
        .catch(() => false);
      await chrome.permissions
        .remove({ permissions: ["cookies"] })
        .catch(() => false);
    }
    setStatus("Couldn't start the playback check", String(error));
  } finally {
    verifyButton.disabled = false;
  }
}

type StopCaptureResponse =
  ({ ok: true } & StopCaptureResult) | { ok: false; error: string };

async function finishVerification(): Promise<void> {
  stopVerifyButton.disabled = true;
  try {
    const verifyState = await readVerifyState();
    const response = await message<StopCaptureResponse>({
      type: "STOP_CAPTURE",
    });
    if (!response.ok) throw new Error(response.error);
    await clearVerifyState();
    // Whatever follows (a picker, the scan, or its failure) starts from a verified video.
    showInspectStep("scan");
    if (response.drm_detected) {
      if (verifyState?.grantedOrigins.length) {
        await chrome.permissions
          .remove({ origins: verifyState.grantedOrigins })
          .catch(() => false);
        await chrome.permissions
          .remove({ permissions: ["cookies"] })
          .catch(() => false);
      }
      reportDrmBlocked(response.reason ?? "DRM was detected during playback.");
      return;
    }
    if (!verifyState)
      throw new Error("Lost discovery state; inspect the page again");
    activeTabId = verifyState.tabId;
    const frames = await inspectFrames(verifyState.tabId);
    const top = frames.find((f) => f.frameId === 0)?.result;
    if (
      top &&
      top.page_url !== verifyState.discovery.page_url &&
      !isYouTubeUrl(verifyState.discovery.page_url)
    ) {
      throw new Error("The page changed during verification; inspect it again");
    }
    const groups = findVideoGroups(frames, top?.page_title || "");
    const selected = groups?.find(
      (g) =>
        verifyState.discovery.selected_media_id &&
        g.result.selected_media_id === verifyState.discovery.selected_media_id,
    );
    if (groups && !selected) {
      renderVideoPicker(groups, frames, true);
      return;
    }
    const fresh = selected
      ? resolveSelectedGroup(selected, frames)
      : mergeDiscoveryResults(frames);
    discovery = fresh || verifyState.discovery;
    discovery.media_candidates = discovery.media_candidates.map(
      (candidate) =>
        response.candidates.find((c) => c.url === candidate.url) || candidate,
    );
    if (
      !groups &&
      response.candidates.length === 1 &&
      discovery.media_candidates.some(
        (c) => c.url === response.candidates[0]!.url,
      )
    ) {
      discovery.caption_candidates = [
        ...discovery.caption_candidates,
        ...(response.caption_candidates || []),
      ].slice(0, 50);
    }
    if (
      !discovery.media_candidates.length &&
      !isYouTubeUrl(discovery.page_url)
    ) {
      // Renditions of one stream are already folded together by the capture, so several
      // requests left here are different videos (an ad and the main one, say). Offer them
      // rather than silently picking one.
      if (response.candidates.length > 1) {
        renderVideoPicker(
          describeCapturedSources(response.candidates, discovery.page_title).map(
            ({ candidate, label, detail, recommended }) => ({
              frameId: 0,
              label,
              detail,
              recommended,
              result: {
                ...discovery!,
                selected_media_id: undefined,
                media_candidates: [candidate],
                caption_candidates: [],
              },
            }),
          ),
          frames,
          true,
        );
        return;
      }
      discovery = {
        ...discovery,
        media_candidates: response.candidates,
        caption_candidates:
          response.caption_candidates || discovery.caption_candidates,
      };
    }
    if (
      !discovery.media_candidates.length &&
      !discovery.structured_candidates?.length &&
      !isYouTubeUrl(discovery.page_url)
    ) {
      throw new Error(
        "Nothing played while the check was running. Click Find video, then run the check and play the video for a few seconds before coming back.",
      );
    }
    setStatus(
      "The playback check passed.",
      "This video isn't copy-protected. Starting the scan…",
    );
    await startDownload();
  } catch (error) {
    // The capture already detached on the background side (win or lose), so there is
    // nothing left to finish — send the user back to a fresh inspect rather than leaving
    // an "I played it" button that would now do nothing.
    await clearVerifyState().catch(() => undefined);
    showInspectStep("find");
    setStatus("The playback check didn't find a video", String(error));
  } finally {
    stopVerifyButton.disabled = false;
  }
}

let capturing = false;
// The job a finished scan was settled for, so a poll still in flight when polling stopped
// cannot settle it a second time.
let settledJobId: string | undefined;

/** A job that will not change again: nothing left to poll, and nothing left to retry. */
function isScanFinished(job: VideoJob): boolean {
  return (
    ["complete", "partial_success", "cancelled"].includes(job.status) ||
    (job.status === "failed" && !job.can_capture)
  );
}

// Where each job phase falls among the four steps the processing screen shows.
const STEP_BY_PHASE: Record<string, number> = {
  download: 0,
  transcript_lookup: 1,
  transcription: 1,
  upload: 1,
  segmentation: 2,
  embedding: 2,
  insights: 2,
  complete: 3,
};

function renderScanSteps(activeStep: number, stalled: boolean): void {
  for (const [index, step] of scanStepElements.entries()) {
    step.dataset.state =
      index < activeStep
        ? "done"
        : index > activeStep
          ? "pending"
          : stalled
            ? "stalled"
            : "active";
  }
}

/** The inspect screen, reset to its first step. */
function showInspectView(): void {
  showView("inspect");
  discovery = undefined;
  resetVideoPicker();
  showInspectStep("find");
  setStatus("Open the page with your video, then click Find video.");
}

/** The processing screen, set up for a scan that is still running. */
function showScanInProgress(scan: ScannedVideo): void {
  settledJobId = undefined;
  showView("processing");
  processingHeadingElement.textContent = "Scanning video";
  processingTitleElement.textContent = scan.title;
  scanLoaderElement.hidden = false;
  processingNoteElement.hidden = false;
  progressElement.hidden = false;
  progressElement.value = 0;
  scanAnotherButton.hidden = true;
  captureButton.hidden = true;
  stopCaptureButton.hidden = !capturing;
  cancelButton.hidden = false;
  renderScanSteps(0, false);
  setStatus("Starting the scan…");
}

/** The processing screen, stopped: the scan ended without a chat to open. */
function showScanEnded(heading: string, reason: string): void {
  stopPolling();
  showView("processing");
  processingHeadingElement.textContent = heading;
  scanLoaderElement.hidden = true;
  processingNoteElement.hidden = true;
  progressElement.hidden = true;
  captureButton.hidden = true;
  stopCaptureButton.hidden = true;
  cancelButton.hidden = true;
  scanAnotherButton.hidden = false;
  for (const step of scanStepElements)
    if (step.dataset.state === "active") step.dataset.state = "stalled";
  setStatus(reason);
}

function renderJob(job: VideoJob): void {
  progressElement.value = job.progress;
  renderScanSteps(
    STEP_BY_PHASE[job.phase] ?? 0,
    job.status === "failed" || job.status === "cancelled",
  );
  // While capturing, the capture flow's instructions stay on screen and its buttons are
  // driven by it, not by the job, which stays "failed" until the capture is submitted.
  if (!capturing) {
    setStatus(
      job.message,
      job.status === "failed" && job.can_capture
        ? "VidSeek couldn't download this player directly. Click 'Retry with a playback check', reload or replay the video in the page, then come back and click 'I played it, retry'."
        : "",
    );
    captureButton.hidden = !job.can_capture;
  }
  if (job.video_id) void recordScannedVideoId(job.job_id, job.video_id);
  cancelButton.hidden = [
    "complete",
    "partial_success",
    "failed",
    "cancelled",
  ].includes(job.status);
  if (isScanFinished(job)) {
    stopPolling();
    void settleFinishedJob(job);
  }
}

async function settleFinishedJob(job: VideoJob): Promise<void> {
  if (settledJobId === job.job_id || !authSession) return;
  settledJobId = job.job_id;
  const scan = await readScannedVideo(authSession.user.id);
  if (scan?.jobId === job.job_id) await settleScan(scan, job);
}

/**
 * Opens the chat for a finished scan, or says why there is none. The video decides, not the
 * job: a job that failed a late, optional step can still leave a video ready to chat about.
 */
async function settleScan(
  scan: ScannedVideo,
  job: VideoJob | undefined,
  lastError?: string,
): Promise<void> {
  const session = authSession;
  if (!session) return;
  const videoId = job?.video_id ?? scan.videoId;
  if (!videoId || job?.status === "cancelled") {
    showScanEnded(
      job?.status === "cancelled" ? "Scan cancelled" : "Scan failed",
      lastError ||
        job?.message ||
        "The companion no longer has this scan. Inspect the video again.",
    );
    return;
  }
  try {
    const video = await getVideo(session.token, videoId);
    if (authSession !== session) return;
    if (allowsChat(video.stage)) {
      showView("chat");
      await openChat(session.token, video);
      return;
    }
    showScanEnded(
      video.stage === "failed" ? "Scan failed" : "Chat isn't available",
      job?.message ||
        "Processing stopped before this video could be understood.",
    );
  } catch (error) {
    if (authSession === session)
      showScanEnded("Could not open the chat", String(error));
  }
}

/** Returns to a scan after the panel reopens or the user signs back in. */
async function resumeScan(
  scan: ScannedVideo,
  lastError?: string,
): Promise<void> {
  showScanInProgress(scan);
  const job = await getJob(scan.jobToken, scan.jobId).catch(() => undefined);
  if (job && !isScanFinished(job)) {
    renderJob(job);
    startPolling({ jobId: scan.jobId, token: scan.jobToken, grantedOrigins: [] });
    return;
  }
  if (job?.video_id) await recordScannedVideoId(scan.jobId, job.video_id);
  // Marked settled first, so drawing the finished job's steps does not settle it again.
  settledJobId = scan.jobId;
  if (job) renderJob(job);
  await settleScan(scan, job, lastError);
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

interface TrackedJobResponse {
  ok: boolean;
  tracker?: TrackedJob;
  capturing?: boolean;
  verifying?: boolean;
  lastError?: string;
}

/** Picks the screen to show: a verification in progress, this user's scan, or inspect. */
async function restoreSignedInView(): Promise<void> {
  if (!authSession) return;
  const response = await message<TrackedJobResponse>({
    type: "GET_TRACKED_JOB",
  });
  const scan = await readScannedVideo(authSession.user.id);
  if (response.verifying) {
    showInspectView();
    showInspectStep("checking");
    setStatus("Playback check running.", "Now play the video in the page.");
    return;
  }
  if (scan) {
    capturing =
      Boolean(response.capturing) && response.tracker?.jobId === scan.jobId;
    // The job that hit this error is already gone; surface it so the user knows why,
    // rather than leaving the badge as the only trace.
    await resumeScan(scan, response.tracker ? undefined : response.lastError);
    return;
  }
  showInspectView();
  if (!response.tracker && response.lastError)
    setStatus("Chrome download was rejected", response.lastError);
}

/** Cancels whatever is running — a verification or this user's scan — and starts over. */
async function cancelActiveWork(): Promise<void> {
  const verifyState = await readVerifyState();
  const scan = authSession && (await readScannedVideo(authSession.user.id));
  const tracked = await message<TrackedJobResponse>({
    type: "GET_TRACKED_JOB",
  });
  // The background worker tracks one job, which may be another account's scan.
  if (!scan || !tracked.tracker || tracked.tracker.jobId === scan.jobId)
    await message({ type: "CANCEL_TRACKED_JOB" });
  stopPolling();
  if (verifyState?.grantedOrigins.length) {
    await chrome.permissions
      .remove({ origins: verifyState.grantedOrigins })
      .catch(() => false);
    await chrome.permissions
      .remove({ permissions: ["cookies"] })
      .catch(() => false);
  }
  await clearVerifyState();
  if (scan) {
    // Covers a job the background worker lost track of, such as after a browser restart.
    await cancelJob(scan.jobToken, scan.jobId).catch(() => undefined);
    await clearScannedVideo(scan.userId);
  }
  capturing = false;
  showInspectView();
  setStatus("Cancelled.");
}

/** Leaves a finished scan or its chat for a new one. The chat stays on the website. */
async function scanAnotherVideo(): Promise<void> {
  if (authSession) await clearScannedVideo(authSession.user.id);
  stopPolling();
  capturing = false;
  showInspectView();
}

inspectButton.addEventListener("click", () => void inspectTab());
downloadButton.addEventListener("click", () => void startDownload());
verifyButton.addEventListener("click", () => void startVerification());
stopVerifyButton.addEventListener("click", () => void finishVerification());
for (const button of [cancelButton, cancelVerifyButton]) {
  button.addEventListener("click", () => {
    button.disabled = true;
    void cancelActiveWork()
      .catch((error: unknown) => setStatus("Could not cancel", String(error)))
      .finally(() => {
        button.disabled = false;
      });
  });
}
for (const button of [scanAnotherButton, chatScanAnotherButton]) {
  button.addEventListener("click", () => void scanAnotherVideo());
}
captureButton.addEventListener("click", () => {
  void (async () => {
    const tracked = await message<{ tracker?: TrackedJob }>({
      type: "GET_TRACKED_JOB",
    });
    if (!tracked.tracker || activeTabId === undefined) {
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      activeTabId = tab?.id;
    }
    if (!tracked.tracker || activeTabId === undefined)
      throw new Error("No retryable job or active tab");
    await message({
      type: "START_CAPTURE",
      tabId: activeTabId,
      jobId: tracked.tracker.jobId,
    });
    capturing = true;
    captureButton.hidden = true;
    stopCaptureButton.hidden = false;
    setStatus(
      "Playback check running.",
      "Reload or replay the video in the page, then come back and click 'I played it, retry'.",
    );
  })().catch((error) =>
    setStatus("Couldn't start the playback check", String(error)),
  );
});
stopCaptureButton.addEventListener("click", () => {
  stopCaptureButton.disabled = true;
  void message<StopCaptureResponse>({ type: "STOP_CAPTURE" })
    .then((response) => {
      if (!response.ok) throw new Error(response.error);
      capturing = false;
      stopCaptureButton.hidden = true;
      if (response.drm_detected) {
        reportDrmBlocked(
          response.reason ?? "DRM was detected during playback.",
        );
        return;
      }
      setStatus(
        "Retrying the scan with what the player loaded.",
        "",
      );
    })
    .catch((error: unknown) => {
      capturing = false;
      setStatus("The playback check didn't find a video", String(error));
    })
    .finally(() => {
      stopCaptureButton.disabled = false;
    });
});

authShowLoginButton.addEventListener("click", () => openAuthForm("login"));
authShowSignupButton.addEventListener("click", () => openAuthForm("signup"));
authBackButton.addEventListener("click", () => {
  authView = "welcome";
  authErrorElement.textContent = "";
  authFormElement.reset();
  renderAuth();
});
authFormElement.addEventListener(
  "submit",
  (event) => void handleAuthSubmit(event),
);
authLogoutButton.addEventListener("click", () => void handleAuthLogout());

// Chrome lets the side panel be resized while it's open, so the backdrop is redrawn
// whenever the panel's own box changes rather than only once at load.
let textureResizeFrame: number | undefined;
new ResizeObserver(() => {
  if (textureResizeFrame !== undefined) cancelAnimationFrame(textureResizeFrame);
  textureResizeFrame = requestAnimationFrame(() => {
    if (!authScreenElement.hidden) renderTexture(authTextureContainer);
    else if (currentView && currentView !== "chat")
      renderTexture(appTextureContainer);
  });
}).observe(document.body);

void restoreAuthState();
