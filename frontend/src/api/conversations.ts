import { readEventStream, request, send } from "./client";
import type {
  ConversationDetail,
  ConversationList,
  ConversationSummary,
  CreateConversationRequest,
  RenameConversationRequest,
  SendMessageRequest,
  StreamEvent
} from "./types";

function conversationResource(conversationId: string, suffix = ""): string {
  return `/v1/conversations/${encodeURIComponent(conversationId)}${suffix}`;
}

export function getConversations(
  videoId: string,
  signal?: AbortSignal
): Promise<ConversationList> {
  return request<ConversationList>(
    `/v1/videos/${encodeURIComponent(videoId)}/conversations`,
    { signal }
  );
}

export function createConversation(
  videoId: string,
  input: CreateConversationRequest = {}
): Promise<ConversationDetail> {
  return request<ConversationDetail>(
    `/v1/videos/${encodeURIComponent(videoId)}/conversations`,
    { method: "POST", body: input }
  );
}

export function getConversation(
  conversationId: string,
  signal?: AbortSignal
): Promise<ConversationDetail> {
  return request<ConversationDetail>(conversationResource(conversationId), { signal });
}

export function renameConversation(
  conversationId: string,
  input: RenameConversationRequest
): Promise<ConversationSummary> {
  return request<ConversationSummary>(conversationResource(conversationId), {
    method: "PATCH",
    body: input
  });
}

export function deleteConversation(conversationId: string): Promise<void> {
  return request<void>(conversationResource(conversationId), { method: "DELETE" });
}

export async function* sendConversationMessage(
  conversationId: string,
  input: SendMessageRequest,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const response = await send(conversationResource(conversationId, "/messages"), {
    method: "POST",
    body: input,
    signal
  });
  yield* readEventStream<StreamEvent>(response);
}

export function stopConversation(conversationId: string): Promise<void> {
  return request<void>(conversationResource(conversationId, "/stop"), { method: "POST" });
}
