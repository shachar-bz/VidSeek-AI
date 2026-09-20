import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  renameConversation,
  sendConversationMessage,
  stopConversation
} from "../src/api/conversations";
import { writeToken } from "../src/api/client";
import {
  getPinnedAnswers,
  getPlaybackUrl,
  getVideo,
  getVideoOutline,
  getVideoTranscript,
  pinAnswer,
  unpinAnswer
} from "../src/api/video";

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

describe("video API", () => {
  it("uses every video artifact and pin endpoint", async () => {
    const fetchMock = vi.fn();
    for (let index = 0; index < 5; index += 1) fetchMock.mockResolvedValueOnce(jsonResponse({}));
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ pin_id: "pin-1" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await getVideo("video/1");
    await getPlaybackUrl("video/1");
    await getVideoTranscript("video/1");
    await getVideoOutline("video/1");
    await getPinnedAnswers("video/1");
    await pinAnswer("video/1", { message_id: "message/1" });
    await unpinAnswer("video/1", "message/1");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/v1/videos/video%2F1",
      "/v1/videos/video%2F1/playback",
      "/v1/videos/video%2F1/transcript",
      "/v1/videos/video%2F1/outline",
      "/v1/videos/video%2F1/pins",
      "/v1/videos/video%2F1/pins",
      "/v1/videos/video%2F1/pins/message%2F1"
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[5]?.[1]?.body))).toEqual({
      message_id: "message/1"
    });
    expect(fetchMock.mock.calls[6]?.[1]?.method).toBe("DELETE");
  });
});

describe("conversation API", () => {
  it("uses the management endpoints and preserves exact request text", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ conversations: [] }))
      .mockResolvedValueOnce(jsonResponse({ conversation_id: "conversation-1" }))
      .mockResolvedValueOnce(jsonResponse({ messages: [] }))
      .mockResolvedValueOnce(jsonResponse({ conversation_id: "conversation-1" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await getConversations("video/1");
    await createConversation("video/1", { first_message: "  Keep this exact  " });
    await getConversation("conversation/1");
    await renameConversation("conversation/1", { title: "New title" });
    await deleteConversation("conversation/1");
    await stopConversation("conversation/1");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/v1/videos/video%2F1/conversations",
      "/v1/videos/video%2F1/conversations",
      "/v1/conversations/conversation%2F1",
      "/v1/conversations/conversation%2F1",
      "/v1/conversations/conversation%2F1",
      "/v1/conversations/conversation%2F1/stop"
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      first_message: "  Keep this exact  "
    });
    expect(fetchMock.mock.calls.map((call) => call[1]?.method)).toEqual([
      "GET",
      "POST",
      "GET",
      "PATCH",
      "DELETE",
      "POST"
    ]);
  });

  it("streams message events through send and propagates the abort signal", async () => {
    const event = {
      type: "message_start",
      user_message_id: "user-1",
      message_id: "assistant-1"
    } as const;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(`event: message\ndata: ${JSON.stringify(event)}\n\n`, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const events = [];
    for await (const received of sendConversationMessage(
      "conversation/1",
      { content: "  exact question  " },
      controller.signal
    )) {
      events.push(received);
    }

    expect(events).toEqual([event]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/conversations/conversation%2F1/messages",
      expect.objectContaining({ method: "POST", signal: controller.signal })
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      content: "  exact question  "
    });
  });
});
