import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  changePassword,
  deleteAccount,
  getSessions,
  revokeAllSessions,
  revokeSession,
  updateAccount
} from "../src/api/account";
import {
  getLibrary,
  getLibraryTags,
  removeLibraryVideo,
  updateLibraryVideo
} from "../src/api/library";
import { writeToken } from "../src/api/client";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

beforeEach(() => {
  window.localStorage.clear();
  writeToken("website-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("library API", () => {
  it("uses the full server-side query and preserves explicit null when clearing a rename", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ videos: [], total: 0, limit: 50, offset: 0 }))
      .mockResolvedValueOnce(jsonResponse({ tags: ["work"] }))
      .mockResolvedValueOnce(jsonResponse({ video_id: "video-1" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await getLibrary({
      search: "launch",
      tags: ["work", "demo"],
      source_site: "example.com",
      stage: "ready",
      added_after: "2026-01-01T00:00:00.000Z",
      added_before: "2026-01-31T23:59:59.999Z",
      has_conversations: false,
      sort: "duration",
      direction: "asc",
      limit: 50,
      offset: 0
    });
    await getLibraryTags();
    await updateLibraryVideo("video/1", { custom_title: null, tags: ["work"] });
    await removeLibraryVideo("video/1");

    expect(fetchMock.mock.calls[0]?.[0]).toContain("/v1/library?");
    expect(fetchMock.mock.calls[0]?.[0]).toContain("tags=work&tags=demo");
    expect(fetchMock.mock.calls[0]?.[0]).toContain("has_conversations=false");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/v1/library/tags");
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/v1/library/video%2F1");
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      custom_title: null,
      tags: ["work"]
    });
    expect(fetchMock.mock.calls[3]?.[1]?.method).toBe("DELETE");
  });
});

describe("account API", () => {
  it("uses every fixed account and session endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "u1", email: "a@b.com", display_name: "A" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ sessions: [] }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await updateAccount({ display_name: "A" });
    await changePassword({ current_password: "old-password", new_password: "new-password" });
    await getSessions();
    await revokeSession("session/1");
    await revokeAllSessions();
    await deleteAccount({ password: "new-password" });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/v1/account",
      "/v1/account/password",
      "/v1/auth/sessions",
      "/v1/auth/sessions/session%2F1",
      "/v1/auth/sessions/revoke-all",
      "/v1/account"
    ]);
    expect(fetchMock.mock.calls.map((call) => call[1]?.method)).toEqual([
      "PATCH",
      "POST",
      "GET",
      "DELETE",
      "POST",
      "DELETE"
    ]);
  });
});
