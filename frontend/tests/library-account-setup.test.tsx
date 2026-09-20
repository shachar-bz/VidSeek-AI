import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { writeToken } from "../src/api/client";
import { useAccount, AccountProvider } from "../src/auth";
import { AccountPage } from "../src/pages/account";
import { LibraryPage } from "../src/pages/library";
import { SetupPage } from "../src/pages/setup";
import { AppShell } from "../src/layout";

const USER = { id: "user-1", email: "person@example.com", display_name: "Original" };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function dataStream(items: unknown[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(items.map((item) => `data: ${JSON.stringify(item)}\n\n`).join(""))
        );
        controller.close();
      }
    }),
    { headers: { "Content-Type": "text/event-stream" } }
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("library page", () => {
  it("promotes a live row to a clickable ready video without reordering it", async () => {
    const processing = {
      video_id: null,
      job_id: "job-1",
      title: "Processing first",
      custom_title: null,
      source_site: "video.example",
      source_url: "https://video.example/first",
      duration_seconds: null,
      tags: [],
      added_at: null,
      stage: "downloading",
      progress: 0.2,
      status_message: "Downloading",
      error_code: null,
      conversation_count: 0
    };
    const complete = {
      ...processing,
      video_id: "video-2",
      job_id: "job-2",
      title: "Already complete",
      stage: "ready",
      progress: 1,
      status_message: "Ready",
      added_at: "2026-09-19T10:00:00Z"
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/library/tags") return Promise.resolve(jsonResponse({ tags: [] }));
      if (url === "/v1/library/events") {
        return Promise.resolve(dataStream([{ job_id: "job-1", video_id: "video-1", stage: "ready", progress: 1, status_message: "Ready", error_code: null }]));
      }
      if (url.startsWith("/v1/library?")) {
        return Promise.resolve(jsonResponse({ videos: [processing, complete], total: 2, limit: 50, offset: 0 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    const promoted = await screen.findByRole("link", { name: "Processing first" });
    expect(promoted.getAttribute("href")).toBe("/videos/video-1");
    expect(screen.getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("link")[0]?.textContent)).toEqual([
      "Processing first",
      "Already complete"
    ]);
    expect(screen.getAllByText("Ready").length).toBeGreaterThanOrEqual(2);
  });

  it("explains ingestion in the empty state and the permanent loss in removal confirmation", async () => {
    const ready = {
      video_id: "video-1",
      job_id: null,
      title: "Keep this",
      custom_title: null,
      source_site: "example.com",
      source_url: "https://example.com/video",
      duration_seconds: 90,
      tags: [],
      added_at: "2026-09-19T10:00:00Z",
      stage: "ready",
      progress: 1,
      status_message: "Ready",
      error_code: null,
      conversation_count: 1
    };
    let pageVideos: unknown[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/library/tags") return Promise.resolve(jsonResponse({ tags: [] }));
      if (url === "/v1/library/events") return Promise.resolve(dataStream([]));
      if (url.startsWith("/v1/library?")) return Promise.resolve(jsonResponse({ videos: pageVideos, total: pageVideos.length, limit: 50, offset: 0 }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    expect(await screen.findByText("Your library is ready for its first video")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Install the Chrome extension" }).getAttribute("href")).toContain("chrome-extension");
    expect(screen.getByText(/website cannot ingest URLs or files/i)).toBeTruthy();

    pageVideos = [ready];
    view.unmount();
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Keep this" }));
    expect(screen.getByText(/re-adding the video later restores its shared video content and artifacts/i)).toBeTruthy();
    expect(screen.getByText(/conversation history is permanently lost/i)).toBeTruthy();
  });
});

describe("library shell notifications", () => {
  it("announces a video that finishes during the current open session", async () => {
    writeToken("token");
    const processing = {
      video_id: null,
      job_id: "job-live",
      title: "Water cycle",
      custom_title: null,
      source_site: "youtube.com",
      source: "youtube_pipeline",
      source_url: "https://youtube.com/watch?v=one",
      duration_seconds: null,
      thumbnail_url: null,
      tags: [],
      added_at: null,
      stage: "transcribing",
      progress: 0.5,
      status_message: "Transcribing",
      error_code: null,
      conversation_count: 0
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/auth/me") return Promise.resolve(jsonResponse(USER));
      if (url === "/v1/library?limit=200") {
        return Promise.resolve(jsonResponse({ videos: [processing], total: 1, limit: 200, offset: 0 }));
      }
      if (url === "/v1/library/events") {
        return Promise.resolve(dataStream([{ job_id: "job-live", video_id: "video-live", stage: "ready", progress: 1, status_message: "Ready", error_code: null }]));
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    render(<MemoryRouter><AccountProvider><AppShell><p>Library content</p></AppShell></AccountProvider></MemoryRouter>);

    const bell = await screen.findByRole("button", { name: "Notifications, 1 unread" });
    fireEvent.click(bell);
    expect(screen.getByText("Water cycle")).toBeTruthy();
    expect(screen.getByText(/ready to search/i)).toBeTruthy();
  });
});

function AccountState() {
  const account = useAccount();
  return <output>{account.status === "authenticated" ? account.user.display_name : account.status}</output>;
}

describe("account page", () => {
  it("synchronizes a changed display name into the shared account context", async () => {
    writeToken("token");
    const updated = { ...USER, display_name: "Updated name" };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/v1/auth/me") return Promise.resolve(jsonResponse(USER));
      if (url === "/v1/auth/sessions") return Promise.resolve(jsonResponse({ sessions: [] }));
      if (url === "/v1/account" && init?.method === "PATCH") return Promise.resolve(jsonResponse(updated));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><AccountProvider><AccountState /><AccountPage /></AccountProvider></MemoryRouter>);
    const name = await screen.findByLabelText(/Display name/);
    fireEvent.change(name, { target: { value: "Updated name" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() => expect(screen.getByText("Display name updated.")).toBeTruthy());
    expect(screen.getByText("Updated name", { selector: "output" })).toBeTruthy();
  });

  it("revoking the current session clears this tab", async () => {
    writeToken("token");
    const session = {
      session_id: "session-1",
      surface: "website",
      created_at: "2026-09-19T09:00:00Z",
      last_used_at: "2026-09-20T09:00:00Z",
      expires_at: "2026-10-20T09:00:00Z",
      current: true
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/auth/me") return Promise.resolve(jsonResponse(USER));
      if (url === "/v1/auth/sessions") return Promise.resolve(jsonResponse({ sessions: [session] }));
      if (url === "/v1/auth/sessions/session-1" || url === "/v1/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><AccountProvider><AccountState /><AccountPage /></AccountProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke and sign out" }));
    await waitFor(() => expect(screen.getByText("unauthenticated", { selector: "output" })).toBeTruthy());
    expect(window.localStorage.getItem("vidseek.auth.token")).toBeNull();
  });

  it("states exactly what account deletion removes and preserves", async () => {
    writeToken("token");
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/auth/me") return Promise.resolve(jsonResponse(USER));
      if (url === "/v1/auth/sessions") return Promise.resolve(jsonResponse({ sessions: [] }));
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<MemoryRouter><AccountProvider><AccountPage /></AccountProvider></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Delete account" }));
    expect(screen.getByText(/removes your user, private library links, conversations, and pins/i)).toBeTruthy();
    expect(screen.getByText(/shared video data and artifacts remain available to other users/i)).toBeTruthy();
  });
});

describe("setup page", () => {
  it("covers the four external setup steps without offering website ingestion", () => {
    render(<MemoryRouter><SetupPage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Install the Chrome extension" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Run the local companion" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sign in with the same account" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Send a video to your library" })).toBeTruthy();
    expect(screen.getByText(/does not ingest URLs or files itself/i)).toBeTruthy();
  });
});
