import type { AuthSession, AuthUser, BrowserContext, DiscoveryResult, MediaCandidate, VideoJob } from "./types";

const COMPANION_URL = "http://127.0.0.1:8765";

async function companionFetch<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
  userToken?: string
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (userToken) headers.set("X-VidSeek-User-Token", userToken);
  const response = await fetch(`${COMPANION_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(describeDetail(payload.detail) || response.statusText);
  }
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
        const entry = item as { location?: unknown[]; message?: string };
        const field = Array.isArray(entry.location) ? entry.location.join(".") : "";
        return field ? `${field}: ${entry.message ?? ""}` : String(entry.message ?? "");
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
  const response = await companionFetch<{ token: string }>("/v1/session", { method: "POST" });
  return response.token;
}

export async function signUp(email: string, password: string, displayName: string): Promise<AuthSession> {
  return companionFetch<AuthSession>("/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName || undefined })
  });
}

export async function logIn(email: string, password: string): Promise<AuthSession> {
  return companionFetch<AuthSession>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
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
  browserContext: BrowserContext
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    "/v1/video-jobs",
    { method: "POST", body: JSON.stringify({ ...discovery, browser_context: browserContext }) },
    token,
    userToken
  );
}

export async function getJob(token: string, jobId: string): Promise<VideoJob> {
  return companionFetch<VideoJob>(`/v1/video-jobs/${encodeURIComponent(jobId)}`, {}, token);
}

export async function cancelJob(token: string, jobId: string): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
    token
  );
}

export async function reportBrowserDownload(
  token: string,
  jobId: string,
  localPath: string
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/download-complete`,
    { method: "POST", body: JSON.stringify({ local_path: localPath }) },
    token
  );
}

export async function retryWithCapture(
  token: string,
  jobId: string,
  candidates: MediaCandidate[],
  browserContext: BrowserContext
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    `/v1/video-jobs/${encodeURIComponent(jobId)}/capture`,
    {
      method: "POST",
      body: JSON.stringify({
        media_candidates: candidates,
        browser_context: browserContext
      })
    },
    token
  );
}
