import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ConversationWorkspace, pinnedAnswerPreview } from "../src/pages/video/ConversationWorkspace";
import type { VideoDetail } from "../src/api/types";

const data = vi.hoisted(() => ({ getConversation: vi.fn() }));
vi.mock("../src/api/conversations", () => ({
  getConversation: data.getConversation,
  getConversations: vi.fn(async () => ({conversations: []})),
  createConversation: vi.fn(), deleteConversation: vi.fn(), renameConversation: vi.fn(),
  sendConversationMessage: vi.fn(), stopConversation: vi.fn()
}));
vi.mock("../src/api/video", () => ({
  getPinnedAnswers: vi.fn(async () => ({pins: [{pin_id: "p1", message_id: "m1", conversation_id: "c1", content: "A useful answer. ".repeat(30), pinned_at: "2026-09-27"}]})),
  pinAnswer: vi.fn(), unpinAnswer: vi.fn()
}));

describe("pinned answer previews", () => {
  it("keeps short answers intact and abbreviates long Unicode answers", () => {
    expect(pinnedAnswerPreview("Short\n answer")).toBe("Short answer");
    expect(pinnedAnswerPreview("a".repeat(160))).toBe("a".repeat(160));
    expect(pinnedAnswerPreview("😀".repeat(161))).toBe("😀".repeat(160) + "…");
  });

  it("opens the source chat and focuses the exact answer, including repeated clicks", async () => {
    data.getConversation.mockResolvedValue({conversation_id: "c1", video_id: "v1", messages: [
      {message_id: "m1", role: "assistant", content: "Target answer", created_at: "2026-09-27", pinned: true},
      {message_id: "m2", role: "assistant", content: "Later answer", created_at: "2026-09-27", pinned: false}
    ]});
    const video = {video_id: "v1", stage: "ready", insights: null} as VideoDetail;
    render(<MemoryRouter initialEntries={["/videos/v1"]}><Routes>
      <Route path="/videos/:videoId" element={<ConversationWorkspace video={video} onSeek={vi.fn()} />} />
    </Routes></MemoryRouter>);
    const pin = await screen.findByRole("link", {name: /^Open pinned answer:/});
    expect(pin.textContent?.length).toBeLessThanOrEqual(161);
    expect(pin.getAttribute("href")).toBe("/videos/v1?conversation=c1&message=m1");
    fireEvent.click(pin);
    await waitFor(() => expect(document.activeElement?.id).toBe("message-m1"));
    screen.getByLabelText("Ask about this video").focus();
    fireEvent.click(pin);
    await waitFor(() => expect(document.activeElement?.id).toBe("message-m1"));
    expect(data.getConversation).toHaveBeenCalledTimes(1);
  });
});
