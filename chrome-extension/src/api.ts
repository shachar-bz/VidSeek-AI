// Requests to the local companion and shared error handling.
import { readEventStream } from "./answer-stream";
import type {
  AuthSession,
  AuthUser,
  BrowserContext,
  CaptionCandidate,
  ConversationDetail,
  ConversationList,
  ConversationSummary,
  DiscoveryResult,
  MediaCandidate,
  SendMessageRequest,
  StreamEvent,
  VideoDetail,
  VideoJob,
} from "./types";

const COMPANION_URL = "http://127.0.0.1:8765";

/** Issues one request and hands back the raw response, raising on any refusal. */
async function companionRequest(
  path: string,
  init: RequestInit = {},
  token?: string,
  userToken?: string,
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (userToken) headers.set("X-VidSeek-User-Token", userToken);
  const response = await fetch(`${COMPANION_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(describeDetail(payload.detail) || response.statusText);
  }
  return response;
}

async function companionFetch<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
  userToken?: string,
): Promise<T> {
  const response = await companionRequest(path, init, token, userToken);
  // /v1/auth/logout answers 204 with no body; parsing that as JSON would throw.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The companion returns a plain string for policy errors and a list for 422s. */
function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const entry = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(entry.loc) ? entry.loc.join(".") : "";
        return field ? `${field}: ${entry.msg ?? ""}` : String(entry.msg ?? "");
      })
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

export interface CompanionHealth {
  status: string;
  download_root: string;
}

export async function getHealth(): Promise<CompanionHealth> {
  return companionFetch<CompanionHealth>("/health");
}

export async function createSession(): Promise<string> {
  const response = await companionFetch<{ token: string }>("/v1/session", {
    method: "POST",
  });
  return response.token;
}

export async function signUp(
  email: string,
  password: string,
  displayName: string,
): Promise<AuthSession> {
  return companionFetch<AuthSession>("/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      display_name: displayName || undefined,
    }),
  });
}

export async function logIn(
  email: string,
  password: string,
): Promise<AuthSession> {
  return companionFetch<AuthSession>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchCurrentUser(token: string): Promise<AuthUser> {
  return companionFetch<AuthUser>("/v1/auth/me", {}, token);
}

export async function logOut(token: string): Promise<void> {
  await companionFetch<void>("/v1/auth/logout", { method: "POST" }, token);
}

export async function createJob(
  token: string,
  userToken: string,
  discovery: DiscoveryResult,
  browserContext: BrowserContext,
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    "/v1/video-jobs",
    {
      method: "POST",
      body: JSON.stringify({ ...discovery, browser_context: browserContext }),
    },
    token,
    userToken,
  );
}

export async function getJob(token: string, jobId: string): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}`,
    {},
    token,
  );
}

export async function cancelJob(
  token: string,
  jobId: string,
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
    token,
  );
}

export async function reportBrowserDownload(
  token: string,
  jobId: string,
  localPath: string,
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/download-complete`,
    { method: "POST", body: JSON.stringify({ local_path: localPath }) },
    token,
  );
}

export async function retryWithCapture(
  token: string,
  jobId: string,
  candidates: MediaCandidate[],
  browserContext: BrowserContext,
  captions: CaptionCandidate[] = [],
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/capture`,
    {
      method: "POST",
      body: JSON.stringify({
        media_candidates: candidates,
        caption_candidates: captions,
        browser_context: browserContext,
      }),
    },
    token,
  );
}

// The calls below authenticate as the signed-in user, whose token is the bearer token here
// rather than the separate header the job calls carry it in.

export async function getVideo(
  userToken: string,
  videoId: string,
): Promise<VideoDetail> {
  return companionFetch<VideoDetail>(
    `/v1/videos/${encodeURIComponent(videoId)}`,
    {},
    userToken,
  );
}

export async function listConversations(
  userToken: string,
  videoId: string,
): Promise<ConversationList> {
  return companionFetch<ConversationList>(
    `/v1/videos/${encodeURIComponent(videoId)}/conversations`,
    {},
    userToken,
  );
}

export async function createConversation(
  userToken: string,
  videoId: string,
): Promise<ConversationDetail> {
  return companionFetch<ConversationDetail>(
    `/v1/videos/${encodeURIComponent(videoId)}/conversations`,
    { method: "POST", body: JSON.stringify({}) },
    userToken,
  );
}

export async function getConversation(
  userToken: string,
  conversationId: string,
): Promise<ConversationDetail> {
  return companionFetch<ConversationDetail>(
    `/v1/conversations/${encodeURIComponent(conversationId)}`,
    {},
    userToken,
  );
}

/** Asks one question and yields the answer's events as they arrive. */
export async function* sendConversationMessage(
  userToken: string,
  conversationId: string,
  body: SendMessageRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await companionRequest(
    `/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: "POST", body: JSON.stringify(body), signal },
    userToken,
  );
  yield* readEventStream(response);
}

export async function stopConversation(
  userToken: string,
  conversationId: string,
): Promise<void> {
  await companionFetch<unknown>(
    `/v1/conversations/${encodeURIComponent(conversationId)}/stop`,
    { method: "POST" },
    userToken,
  );
}

export async function renameConversation(
  userToken: string,
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return companionFetch<ConversationSummary>(
    `/v1/conversations/${encodeURIComponent(conversationId)}`,
    { method: "PATCH", body: JSON.stringify({ title }) },
    userToken,
  );
}
