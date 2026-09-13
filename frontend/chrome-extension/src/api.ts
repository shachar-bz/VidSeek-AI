import type { BrowserContext, DiscoveryResult, MediaCandidate, VideoJob } from "./types";

export const COMPANION_URL = "http://127.0.0.1:8765";

async function companionFetch<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${COMPANION_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(String(payload.detail || response.statusText));
  }
  return (await response.json()) as T;
}

export async function createSession(): Promise<string> {
  const response = await companionFetch<{ token: string }>("/v1/session", { method: "POST" });
  return response.token;
}

export async function createJob(
  token: string,
  discovery: DiscoveryResult,
  browserContext: BrowserContext
): Promise<VideoJob> {
  return companionFetch<VideoJob>(
    "/v1/video-jobs",
    { method: "POST", body: JSON.stringify({ ...discovery, browser_context: browserContext }) },
    token
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
