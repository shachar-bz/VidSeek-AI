// The one place the website talks to the API: base URL, bearer token, and error shape.
//
// The error shape is the part worth centralising. The API answers a policy error with
// `{"detail": "a sentence"}` and a validation error with `{"detail": [{location, message,
// type}, ...]}` — `api/app.py`'s `redact_validation_errors` builds the second — so every
// caller would otherwise have to know both. `chrome-extension/src/api.ts` solves the same
// problem the same way; this is that function, plus the status code, which the website
// needs because a 401 signs the user out and a 503 does not.

import { STREAM_EVENT_NAME, type StreamEvent } from "./types";

/** Same-origin in production; Vite proxies `/v1` to the API in development. */
const API_BASE = import.meta.env.VITE_API_URL ?? "";

const TOKEN_STORAGE_KEY = "vidseek.auth.token";

/** A request the API refused, with the status the caller has to branch on. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** The session is gone or was revoked: the caller signs out rather than retrying. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/**
 * The stored bearer token, or null when nobody is signed in.
 *
 * Sessions are durable server-side, so a token kept here survives a reload and an API
 * restart. It is still verified on the next request rather than trusted: a token that was
 * revoked from another device fails with a 401 and signs this one out.
 */
export function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    // Storage can be unavailable or blocked; that is a session that does not survive a
    // reload rather than an app that cannot run.
    return null;
  }
}

export function writeToken(token: string | null): void {
  try {
    if (token === null) window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    else window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    /* see readToken */
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Query parameters; undefined and null entries are dropped, arrays repeat the key. */
  query?: Record<string, unknown>;
  signal?: AbortSignal;
  /** Send without the bearer token — signup and login, which do not have one yet. */
  anonymous?: boolean;
}

/** Issue one API request, returning the parsed body and raising `ApiError` on refusal. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Issue one API request and hand back the raw response, for a body that is not JSON.
 *
 * The answer stream is the only such body today. It is read through `fetch` rather than
 * through `EventSource` because `EventSource` can neither set an `Authorization` header nor
 * issue a POST, and an answer is a POST carrying a question.
 */
export async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (!options.anonymous) {
    const token = readToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}${buildQuery(options.query)}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal
  });

  if (!response.ok) throw new ApiError(response.status, await describeFailure(response));
  return response;
}

/** The sentence to show for a refused request, out of either shape the API answers with. */
async function describeFailure(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  const detail = (payload as { detail?: unknown } | null)?.detail;
  return describeDetail(detail) || response.statusText || `Request failed (${response.status})`;
}

export function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "";
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

/** A query string, dropping absent values and repeating a key for each array element. */
export function buildQuery(query: Record<string, unknown> | undefined): string {
  if (!query) return "";
  const parameters = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) for (const item of value) parameters.append(name, String(item));
    else parameters.append(name, String(value));
  }
  const rendered = parameters.toString();
  return rendered ? `?${rendered}` : "";
}

/**
 * Read one server-sent event stream, yielding each payload as it arrives.
 *
 * Written against a `Response` body rather than `EventSource` for the reason `send`
 * explains. It handles the one framing rule this stream uses: events separated by a blank
 * line, each carrying an `event:` name and one or more `data:` lines. A partial event left
 * in the buffer when the stream ends is discarded rather than guessed at.
 */
export async function* readEventStream(response: Response): AsyncGenerator<StreamEvent> {
  const body = response.body;
  if (!body) return;
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const parsed = parseEvent(buffer.slice(0, boundary));
        if (parsed) yield parsed;
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

/** One `event:`/`data:` block as its payload, or null if it is not one this stream sends. */
function parseEvent(block: string): StreamEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) data.push(line.slice("data:".length).trimStart());
  }
  if (name !== STREAM_EVENT_NAME || data.length === 0) return null;
  try {
    return JSON.parse(data.join("\n")) as StreamEvent;
  } catch {
    return null;
  }
}
