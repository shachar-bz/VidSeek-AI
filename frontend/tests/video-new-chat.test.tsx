import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationDetail, VideoDetail } from "../src/api/types";
import { ConversationWorkspace, type PlayerPosition } from "../src/pages/video/ConversationWorkspace";

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  getConversations: vi.fn(),
  renameConversation: vi.fn(),
  sendConversationMessage: vi.fn(),
  stopConversation: vi.fn()
}));
vi.mock("../src/api/conversations", () => api);
vi.mock("../src/api/video", () => ({
  getPinnedAnswers: vi.fn(async () => ({ pins: [] })),
  pinAnswer: vi.fn(),
  unpinAnswer: vi.fn()
}));

const video: VideoDetail = {
  video_id: "video-1",
  title: "The Water Cycle",
  custom_title: null,
  original_title: "The Water Cycle",
  source_site: "www.youtube.com",
  source_url: "https://www.youtube.com/watch?v=abc",
  duration_seconds: 600,
  tags: [],
  added_at: "2026-09-22T10:00:00Z",
  stage: "ready",
  transcript_source: "captions",
  transcript_language: "en",
  transcript_timing_fidelity: "caption",
  conversation_count: 0,
  visual_status: "ready",
  insights: null
};

const created: ConversationDetail = {
  conversation_id: "conversation-1",
  video_id: "video-1",
  title: null,
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  messages: []
};

function renderWorkspace(playerPosition?: () => PlayerPosition | null) {
  return render(
    <MemoryRouter initialEntries={["/videos/video-1"]}>
      <Routes>
        <Route path="/videos/:videoId" element={<ConversationWorkspace video={video} approximate={false} onSeek={vi.fn()} playerPosition={playerPosition} />} />
      </Routes>
    </MemoryRouter>
  );
}

async function sendFirstMessage(text: string) {
  await screen.findByText("No chats yet.");
  fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
  fireEvent.change(screen.getByLabelText("Ask about this video"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(api.sendConversationMessage).toHaveBeenCalled());
}

describe("a new chat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConversations.mockResolvedValue({ conversations: [] });
    api.createConversation.mockResolvedValue(created);
    api.renameConversation.mockResolvedValue({ ...created, title: "Chat 1", message_count: 0 });
    api.sendConversationMessage.mockImplementation(async function* () { /* no events */ });
  });

  it("is not stored when it is opened and left without typing", async () => {
    renderWorkspace();
    await screen.findByText("No chats yet.");

    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));

    expect(screen.getByLabelText("Ask about this video")).toBeTruthy();
    expect(api.createConversation).not.toHaveBeenCalled();
  });

  it("is stored when its first message is sent, and that message goes to it", async () => {
    renderWorkspace();
    await screen.findByText("No chats yet.");

    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
    fireEvent.change(screen.getByLabelText("Ask about this video"), { target: { value: "What is evaporation?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(api.sendConversationMessage).toHaveBeenCalled());
    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(api.renameConversation).toHaveBeenCalledWith("conversation-1", { title: "Chat 1" });
    expect(api.sendConversationMessage.mock.calls[0]?.slice(0, 2)).toEqual(["conversation-1", { content: "What is evaporation?" }]);
    expect(await screen.findByText("Chat 1")).toBeTruthy();
  });

  it("sends where the player was, so 'what is this?' has a moment to point at", async () => {
    renderWorkspace(() => ({ seconds: 312.4, paused: true }));
    await sendFirstMessage("What is this diagram?");

    expect(api.sendConversationMessage.mock.calls[0]?.[1]).toEqual({
      content: "What is this diagram?",
      current_time_seconds: 312.4,
      player_paused: true
    });
  });

  it("says when the player was still playing, so the moment may be a little earlier", async () => {
    renderWorkspace(() => ({ seconds: 40, paused: false }));
    await sendFirstMessage("What is he doing?");

    expect(api.sendConversationMessage.mock.calls[0]?.[1]).toEqual({
      content: "What is he doing?",
      current_time_seconds: 40,
      player_paused: false
    });
  });

  it("sends no position when the player has none to give", async () => {
    renderWorkspace(() => null);
    await sendFirstMessage("What is evaporation?");

    expect(api.sendConversationMessage.mock.calls[0]?.[1]).toEqual({ content: "What is evaporation?" });
  });
});
