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

export async function* subscribeToLibraryEvents(
  signal?: AbortSignal
): AsyncGenerator<LibraryProgressEvent> {
  const response = await send("/v1/library/events", { signal });
  yield* readEventStream<LibraryProgressEvent>(response);
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
