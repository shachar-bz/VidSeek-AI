import { ApiError, readEventStream, request, send } from "./client";
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

/** How long to wait before reconnecting, by how many attempts in a row have failed. */
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 30_000];

interface LibraryEventSubscriber {
  deliver(event: LibraryProgressEvent): void;
  fail(error: unknown): void;
}

// One progress connection shared by every subscriber (the notification bell and the library
// page), open while anyone is subscribed. The last event of each job is kept so a subscriber
// that joins later starts from the same snapshot a fresh connection would have sent it.
const libraryEventSubscribers = new Set<LibraryEventSubscriber>();
const latestEventByJob = new Map<string, { event: LibraryProgressEvent; serialized: string }>();
let sharedLibraryConnection: AbortController | null = null;

/**
 * Every job's current progress, then each change as the API pushes it, until `signal` aborts.
 *
 * The stream stays open while nothing is processing, so a video the extension sends later
 * shows up here too. A dropped connection is retried with backoff; only a refusal that
 * retrying cannot fix, such as a revoked session, ends the subscription with an error.
 */
export async function* subscribeToLibraryEvents(
  signal?: AbortSignal
): AsyncGenerator<LibraryProgressEvent> {
  const queue = Array.from(latestEventByJob.values(), (latest) => latest.event);
  let failure: { error: unknown } | null = null;
  let wake: (() => void) | null = null;
  const subscriber: LibraryEventSubscriber = {
    deliver(event) {
      queue.push(event);
      wake?.();
    },
    fail(error) {
      failure = { error };
      wake?.();
    }
  };
  const onAbort = () => wake?.();
  signal?.addEventListener("abort", onAbort, { once: true });
  libraryEventSubscribers.add(subscriber);
  if (!sharedLibraryConnection) openSharedLibraryConnection();

  try {
    while (!signal?.aborted) {
      const next = queue.shift();
      if (next) {
        yield next;
        continue;
      }
      if (failure) throw (failure as { error: unknown }).error;
      await new Promise<void>((resolve) => {
        wake = resolve;
      });
      wake = null;
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
    libraryEventSubscribers.delete(subscriber);
    if (libraryEventSubscribers.size === 0) closeSharedLibraryConnection();
  }
}

function openSharedLibraryConnection(): void {
  const connection = new AbortController();
  sharedLibraryConnection = connection;
  void runSharedLibraryConnection(connection);
}

function closeSharedLibraryConnection(): void {
  sharedLibraryConnection?.abort();
  sharedLibraryConnection = null;
  // Nobody is listening, so nothing keeps these current; the next connection resends them.
  latestEventByJob.clear();
}

async function runSharedLibraryConnection(connection: AbortController): Promise<void> {
  const { signal } = connection;
  let failedAttempts = 0;
  while (!signal.aborted) {
    try {
      const response = await send("/v1/library/events", { signal });
      failedAttempts = 0;
      for await (const event of readEventStream<LibraryProgressEvent>(response)) {
        if (signal.aborted) return;
        publishLibraryEvent(event);
      }
    } catch (error) {
      if (signal.aborted) return;
      if (isPermanentRefusal(error)) {
        if (sharedLibraryConnection === connection) sharedLibraryConnection = null;
        for (const subscriber of libraryEventSubscribers) subscriber.fail(error);
        return;
      }
      failedAttempts += 1;
    }
    await waitForReconnect(failedAttempts, signal);
  }
}

/** Hand an event to every subscriber, unless it repeats what they already have. */
function publishLibraryEvent(event: LibraryProgressEvent): void {
  const serialized = JSON.stringify(event);
  // A reconnect resends every job's state; only the ones that changed meanwhile are news.
  if (latestEventByJob.get(event.job_id)?.serialized === serialized) return;
  latestEventByJob.set(event.job_id, { event, serialized });
  for (const subscriber of libraryEventSubscribers) subscriber.deliver(event);
}

/** A client error retrying cannot fix: a 4xx, except a 429 that only asks to slow down. */
function isPermanentRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429;
}

function waitForReconnect(failedAttempts: number, signal: AbortSignal): Promise<void> {
  const delay = RECONNECT_DELAYS_MS[Math.min(failedAttempts, RECONNECT_DELAYS_MS.length - 1)];
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, delay);
    signal.addEventListener("abort", () => {
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
