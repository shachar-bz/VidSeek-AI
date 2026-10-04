import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ConversationWorkspace, PINNED_PREVIEW_MAX_CHARS, groupPinsByConversation, pinnedAnswerPreview } from "../src/pages/video/ConversationWorkspace";
import type { VideoDetail } from "../src/api/types";

const data = vi.hoisted(() => ({ getConversation: vi.fn() }));
vi.mock("../src/api/conversations", () => ({
  getConversation: data.getConversation,
  getConversations: vi.fn(async () => ({conversations: [{conversation_id: "c1", video_id: "v1", title: "Renamed chat", created_at: "2026-09-27", updated_at: "2026-09-27", message_count: 2}]})),
  createConversation: vi.fn(), deleteConversation: vi.fn(), renameConversation: vi.fn(),
  sendConversationMessage: vi.fn(), stopConversation: vi.fn()
}));
vi.mock("../src/api/video", () => ({
  getPinnedAnswers: vi.fn(async () => ({pins: [{pin_id: "p1", message_id: "m1", conversation_id: "c1", content: "A useful answer. ".repeat(30), message_created_at: "2026-09-27T14:37:00Z", pinned_at: "2026-09-27"}]})),
  pinAnswer: vi.fn(), unpinAnswer: vi.fn()
}));

describe("pinned answer previews", () => {
  it("keeps short answers intact and abbreviates long Unicode answers", () => {
    expect(pinnedAnswerPreview("Short\n answer")).toBe("Short answer");
    expect(pinnedAnswerPreview("a".repeat(PINNED_PREVIEW_MAX_CHARS))).toBe("a".repeat(PINNED_PREVIEW_MAX_CHARS));
    expect(pinnedAnswerPreview("😀".repeat(PINNED_PREVIEW_MAX_CHARS + 1))).toBe("😀".repeat(PINNED_PREVIEW_MAX_CHARS) + "...");
    expect(pinnedAnswerPreview("abcdef", 3)).toBe("abc...");
  });

  it("groups pins by source chat in the order the pins arrive", () => {
    const pin = (pin_id: string, conversation_id: string) => ({pin_id, message_id: `m-${pin_id}`, conversation_id, content: "x", message_created_at: "2026-09-27", pinned_at: "2026-09-27"});
    const groups = groupPinsByConversation([pin("p1", "c2"), pin("p2", "c1"), pin("p3", "c2")]);
    expect(groups.map((group) => [group.conversation_id, group.pins.map((item) => item.pin_id)])).toEqual([["c2", ["p1", "p3"]], ["c1", ["p2"]]]);
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
    expect(pin.textContent?.length).toBeLessThanOrEqual(PINNED_PREVIEW_MAX_CHARS + 3);
    expect(pin.getAttribute("href")).toBe("/videos/v1?conversation=c1&message=m1");
    fireEvent.click(pin);
    await waitFor(() => expect(document.activeElement?.id).toBe("message-m1"));
    screen.getByLabelText("Ask about this video").focus();
    fireEvent.click(pin);
    await waitFor(() => expect(document.activeElement?.id).toBe("message-m1"));
    expect(data.getConversation).toHaveBeenCalledTimes(1);
  });

  it("shows the current chat title once as the group header and gives each pin its own unpin control", async () => {
    const video = {video_id: "v1", stage: "ready", insights: null} as VideoDetail;
    render(<MemoryRouter initialEntries={["/videos/v1"]}><Routes>
      <Route path="/videos/:videoId" element={<ConversationWorkspace video={video} onSeek={vi.fn()} />} />
    </Routes></MemoryRouter>);
    const group = await screen.findByRole("region", {name: "Renamed chat"});
    expect(group.querySelector("h3")?.textContent).toBe("Renamed chat");
    expect(group.querySelectorAll("li")).toHaveLength(1);
    expect(group.querySelector("time")?.getAttribute("datetime")).toBe("2026-09-27T14:37:00Z");
    expect(screen.getAllByRole("button", {name: /^Unpin answer:/})).toHaveLength(1);
  });
});
