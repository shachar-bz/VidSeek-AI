// Chats started in the extension are numbered the way the website numbers its own.
import { describe, expect, it } from "vitest";

import { nextChatName } from "../src/chat-names";
import type { ConversationSummary } from "../src/types";

const summary = (title: string | null): ConversationSummary => ({
  conversation_id: `c-${title}`,
  video_id: "v",
  title,
  created_at: "t",
  updated_at: "t",
  message_count: 0,
});

describe("naming a new chat", () => {
  it("continues after the highest Chat N, ignoring renamed and untitled chats", () => {
    expect(nextChatName([])).toBe("Chat 1");
    expect(nextChatName([summary("Chat 1"), summary("Chat 2")])).toBe("Chat 3");
    expect(
      nextChatName([summary("Water cycle questions"), summary(null), summary("Chat 4")]),
    ).toBe("Chat 5");
  });
});
