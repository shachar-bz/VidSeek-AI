// Numbers new chats "Chat N" the same way the website does, so both list them alike.
import type { ConversationSummary } from "./types";

const CHAT_NAME = /^Chat (\d+)$/;

/**
 * The next chat continues the highest `Chat N` the video already has, so a renamed chat
 * never gives its number back. Mirrors `nextChatName` in the website's ConversationWorkspace.
 */
export function nextChatName(conversations: ConversationSummary[]): string {
  const highest = conversations.reduce((current, conversation) => {
    const match = CHAT_NAME.exec(conversation.title ?? "");
    return match ? Math.max(current, Number(match[1])) : current;
  }, 0);
  return `Chat ${highest + 1}`;
}
