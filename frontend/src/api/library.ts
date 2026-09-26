import { readEventStream, request, send } from "./client";
import type {
  LibraryPage,
  LibraryProgressEvent,
  LibraryQuery,
  LibraryVideo,
  TagList,
  UpdateLibraryLinkRequest
} from "./types";

export function getLibrary(query: LibraryQuery = {}, signal?: AbortSignal): Promise<LibraryPage> {
  return request<LibraryPage>("/v1/library", { query: { ...query }, signal });
}

export function getLibraryTags(signal?: AbortSignal): Promise<TagList> {
  return request<TagList>("/v1/library/tags", { signal });
}

export async function getLibraryThumbnail(
  thumbnailUrl: string,
  signal?: AbortSignal
): Promise<Blob> {
  const response = await send(thumbnailUrl, { signal });
  return response.blob();
}

export async function* subscribeToLibraryEvents(
  signal?: AbortSignal
): AsyncGenerator<LibraryProgressEvent> {
  while (!signal?.aborted) {
    const response = await send("/v1/library/events", { signal });
    yield* readEventStream<LibraryProgressEvent>(response);
    if (signal?.aborted) return;
    await waitForReconnect(signal);
  }
}

function waitForReconnect(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, 1500);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(timeout);
      resolve();
    }, { once: true });
  });
}

export function updateLibraryVideo(
  videoId: string,
  update: UpdateLibraryLinkRequest
): Promise<LibraryVideo> {
  return request<LibraryVideo>(`/v1/library/${encodeURIComponent(videoId)}`, {
    method: "PATCH",
    body: update
  });
}

export function removeLibraryVideo(videoId: string): Promise<void> {
  return request<void>(`/v1/library/${encodeURIComponent(videoId)}`, { method: "DELETE" });
}

/** Dismisses a job that failed before producing a video, which has no library link to remove. */
export function removeFailedLibraryJob(jobId: string): Promise<void> {
  return request<void>(`/v1/library/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}
