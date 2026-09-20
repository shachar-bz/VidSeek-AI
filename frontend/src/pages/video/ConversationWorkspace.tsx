import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  renameConversation,
  sendConversationMessage,
  stopConversation
} from "../../api/conversations";
import { ApiError } from "../../api/client";
import {
  allowsChat,
  type ConversationDetail,
  type ConversationMessage,
  type ConversationSummary,
  type PinnedAnswer,
  type VideoDetail
} from "../../api/types";
import { getPinnedAnswers, pinAnswer, unpinAnswer } from "../../api/video";
import { Button, Dialog, EmptyState, Panel } from "../../components/ui";
import { videoPath } from "../../routes";
import { featureFailureMessage } from "../shared";
import { beginGeneration, applyStreamEvent, endIncompleteStream, type LiveGeneration } from "./streamState";
import { ToolTrace } from "./ToolTrace";

export interface SuggestedQuestionRequest {
  requestId: number;
  text: string;
}

function summaryFromDetail(detail: ConversationDetail): ConversationSummary {
  return {
    conversation_id: detail.conversation_id,
    video_id: detail.video_id,
    title: detail.title,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
    message_count: detail.messages.length
  };
}

function newestFirst(conversations: ConversationSummary[]): ConversationSummary[] {
  return [...conversations].sort(
    (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at)
  );
}

function formatLastUsed(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function chatUnavailableMessage(stage: VideoDetail["stage"]): string | null {
  if (allowsChat(stage)) return null;
  if (stage === "failed") return "Chat is unavailable because processing failed.";
  return `${stage.charAt(0).toUpperCase() + stage.slice(1)} is in progress. Questions become available when processing completes.`;
}

function MessageCard({
  message,
  pinPending,
  onTogglePin
}: {
  message: ConversationMessage;
  pinPending: boolean;
  onTogglePin(message: ConversationMessage): void;
}) {
  return (
    <article className={`chat-message chat-message--${message.role}`}>
      <header><span>{message.role === "user" ? "You" : "VidSeek"}</span>{message.role === "assistant" ? <Button variant="ghost" pending={pinPending} onClick={() => onTogglePin(message)}>{message.pinned ? "Unpin" : "Pin answer"}</Button> : null}</header>
      <div className="chat-message__content">{message.content || (message.role === "assistant" ? "Waiting for an answer…" : "")}</div>
      {message.role === "assistant" ? <ToolTrace calls={message.tool_trace} /> : null}
    </article>
  );
}

export function ConversationWorkspace({
  video,
  suggestedQuestion
}: {
  video: VideoDetail;
  suggestedQuestion: SuggestedQuestionRequest | null;
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedId = searchParams.get("conversation");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [pins, setPins] = useState<PinnedAnswer[]>([]);
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<LiveGeneration | null>(null);
  const liveRef = useRef<LiveGeneration | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [pinPending, setPinPending] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const generationRef = useRef(0);
  const streamControllerRef = useRef<AbortController | null>(null);
  const handledSuggestionRef = useRef(0);
  const canChat = allowsChat(video.stage);

  const updateLive = useCallback((next: LiveGeneration | null) => {
    liveRef.current = next;
    setLive(next);
  }, []);

  const loadConversationList = useCallback(async (signal?: AbortSignal) => {
    const response = await getConversations(video.video_id, signal);
    setConversations(newestFirst(response.conversations));
  }, [video.video_id]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setWorkspaceError(null);
    void Promise.all([loadConversationList(controller.signal), getPinnedAnswers(video.video_id, controller.signal).then((response) => setPins(response.pins))])
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setWorkspaceError(featureFailureMessage(caught, "Conversations and pins could not be loaded."));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loadConversationList, video.video_id]);

  useEffect(() => {
    generationRef.current += 1;
    streamControllerRef.current?.abort();
    streamControllerRef.current = null;
    setStreaming(false);
    updateLive(null);
    setStreamError(null);
    if (!selectedId) {
      setDetail(null);
      setRenameDraft("");
      return;
    }
    const controller = new AbortController();
    setWorkspaceError(null);
    getConversation(selectedId, controller.signal)
      .then((response) => {
        if (response.video_id !== video.video_id) throw new Error("This conversation belongs to another video.");
        setDetail(response);
        setRenameDraft(response.title ?? "");
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setWorkspaceError(featureFailureMessage(caught, "This conversation could not be loaded."));
      });
    return () => controller.abort();
  }, [selectedId, updateLive, video.video_id]);

  const startNewConversation = useCallback(async (prefill = "") => {
    if (!canChat) return;
    setCreating(true);
    setWorkspaceError(null);
    try {
      const created = await createConversation(video.video_id, prefill ? { first_message: prefill } : {});
      setConversations((current) => newestFirst([summaryFromDetail(created), ...current.filter((item) => item.conversation_id !== created.conversation_id)]));
      setDraft(prefill);
      navigate(videoPath(video.video_id, created.conversation_id));
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "A new conversation could not be created."));
    } finally {
      setCreating(false);
    }
  }, [canChat, navigate, video.video_id]);

  useEffect(() => {
    if (!suggestedQuestion || suggestedQuestion.requestId === handledSuggestionRef.current) return;
    handledSuggestionRef.current = suggestedQuestion.requestId;
    void startNewConversation(suggestedQuestion.text);
  }, [startNewConversation, suggestedQuestion]);

  function commitLiveToHistory(current: LiveGeneration, terminalMessage?: ConversationMessage) {
    setDetail((existing) => existing ? {
      ...existing,
      messages: [...existing.messages, current.userMessage, terminalMessage ?? current.assistantMessage]
    } : existing);
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !canChat || !draft.trim() || streaming) return;
    if (liveRef.current) commitLiveToHistory(liveRef.current);
    const content = draft;
    const initial = beginGeneration(content);
    updateLive(initial);
    setDraft("");
    setStreamError(null);
    setStreaming(true);
    const controller = new AbortController();
    streamControllerRef.current = controller;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    let terminal = false;

    try {
      for await (const streamEvent of sendConversationMessage(selectedId, { content }, controller.signal)) {
        if (generationRef.current !== generation) return;
        const current = liveRef.current;
        if (!current) return;
        const next = applyStreamEvent(current, streamEvent);
        updateLive(next);
        if (next.terminal === "complete" || next.terminal === "stopped") {
          terminal = true;
          commitLiveToHistory(next, next.assistantMessage);
          updateLive(null);
          await loadConversationList();
          const refreshed = await getConversation(selectedId);
          if (generationRef.current === generation) {
            setDetail(refreshed);
            setRenameDraft(refreshed.title ?? "");
          }
        } else if (next.terminal === "error") {
          terminal = true;
          setStreamError(next.error);
        }
      }
      if (generationRef.current === generation && !terminal && liveRef.current) {
        const incomplete = endIncompleteStream(liveRef.current);
        updateLive(incomplete);
        setStreamError(incomplete.error);
      }
    } catch (caught) {
      if (generationRef.current !== generation || controller.signal.aborted) return;
      const message = caught instanceof ApiError && caught.status === 503
        ? "Agent not available yet. Video playback, transcript, outline, insights, and pins are still available."
        : featureFailureMessage(caught, "The answer could not be completed.");
      if (liveRef.current) updateLive({ ...liveRef.current, terminal: "error", error: message });
      setStreamError(message);
    } finally {
      if (generationRef.current === generation) {
        setStreaming(false);
        streamControllerRef.current = null;
      }
    }
  }

  async function stop() {
    if (!selectedId || !streaming) return;
    generationRef.current += 1;
    const controller = streamControllerRef.current;
    streamControllerRef.current = null;
    setStreaming(false);
    if (liveRef.current) updateLive({ ...liveRef.current, terminal: "stopped" });
    setStreamError("Generation stopped. The partial answer has been kept.");
    controller?.abort();
    try {
      await stopConversation(selectedId);
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 409)) {
        setStreamError(featureFailureMessage(caught, "The local stream stopped, but the server could not confirm it."));
      }
    }
  }

  async function togglePin(message: ConversationMessage) {
    if (message.role !== "assistant") return;
    setPinPending(message.message_id);
    setWorkspaceError(null);
    try {
      if (message.pinned) {
        await unpinAnswer(video.video_id, message.message_id);
        setPins((current) => current.filter((pin) => pin.message_id !== message.message_id));
      } else {
        const pinned = await pinAnswer(video.video_id, { message_id: message.message_id });
        setPins((current) => [pinned, ...current.filter((pin) => pin.message_id !== pinned.message_id)]);
      }
      const pinned = !message.pinned;
      setDetail((current) => current ? { ...current, messages: current.messages.map((item) => item.message_id === message.message_id ? { ...item, pinned } : item) } : current);
      if (liveRef.current?.assistantMessage.message_id === message.message_id) updateLive({ ...liveRef.current, assistantMessage: { ...liveRef.current.assistantMessage, pinned } });
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "The pin could not be updated."));
    } finally {
      setPinPending(null);
    }
  }

  async function saveRename(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !renameDraft.trim()) return;
    setRenaming(true);
    try {
      const renamed = await renameConversation(selectedId, { title: renameDraft.trim() });
      setConversations((current) => newestFirst(current.map((item) => item.conversation_id === renamed.conversation_id ? renamed : item)));
      setDetail((current) => current ? { ...current, title: renamed.title, updated_at: renamed.updated_at } : current);
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "The conversation could not be renamed."));
    } finally {
      setRenaming(false);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setDeletePending(true);
    try {
      await deleteConversation(deleting.conversation_id);
      setConversations((current) => current.filter((item) => item.conversation_id !== deleting.conversation_id));
      setPins((current) => current.filter((pin) => pin.conversation_id !== deleting.conversation_id));
      if (selectedId === deleting.conversation_id) navigate(videoPath(video.video_id));
      setDeleting(null);
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "The conversation could not be deleted."));
    } finally {
      setDeletePending(false);
    }
  }

  const selectedSummary = conversations.find((item) => item.conversation_id === selectedId) ?? null;
  const renderedMessages = useMemo(() => [
    ...(detail?.messages ?? []),
    ...(live ? [live.userMessage, live.assistantMessage] : [])
  ], [detail?.messages, live]);
  const unavailable = chatUnavailableMessage(video.stage);

  return (
    <section className="conversation-feature" aria-labelledby="conversation-heading">
      <div className="video-section__heading video-section__heading--split"><div><h2 id="conversation-heading">Conversations</h2><p>Ask questions about this video and inspect how VidSeek retrieved the answer.</p></div><Button variant="primary" pending={creating} disabled={!canChat} onClick={() => void startNewConversation()}>{creating ? "Creating…" : "New conversation"}</Button></div>
      {unavailable ? <div className="inline-notice" role="status">{unavailable}</div> : null}
      {workspaceError ? <div className="inline-notice" role="alert">{workspaceError}</div> : null}
      <div className="conversation-grid">
        <Panel className="conversation-list-panel" aria-label="Conversation list">
          {loading ? <p className="muted-text">Loading conversations…</p> : conversations.length === 0 ? <p className="muted-text">No conversations yet.</p> : <ol className="conversation-list">{conversations.map((conversation) => <li key={conversation.conversation_id} className={conversation.conversation_id === selectedId ? "conversation-list__item conversation-list__item--active" : "conversation-list__item"}><button type="button" onClick={() => navigate(videoPath(video.video_id, conversation.conversation_id))}><strong>{conversation.title ?? "New conversation"}</strong><span>{formatLastUsed(conversation.updated_at)}</span></button><Button variant="ghost" aria-label={`Delete ${conversation.title ?? "conversation"}`} onClick={() => setDeleting(conversation)}>×</Button></li>)}</ol>}
        </Panel>
        <Panel className="chat-panel">
          {!selectedId ? <EmptyState title="Choose or start a conversation" description="Each conversation has its own context for this video." /> : !detail ? <p className="muted-text">Loading conversation…</p> : <>
            <form className="conversation-title-form" onSubmit={saveRename}><input aria-label="Conversation title" maxLength={200} value={renameDraft} placeholder="New conversation" onChange={(event) => setRenameDraft(event.target.value)} /><Button variant="ghost" pending={renaming} type="submit" disabled={!renameDraft.trim()}>Rename</Button>{selectedSummary ? <Button className="danger-button" variant="ghost" onClick={() => setDeleting(selectedSummary)}>Delete</Button> : null}</form>
            <div className="chat-history" aria-live="polite">{renderedMessages.length === 0 ? <p className="muted-text">Ask the first question to begin.</p> : renderedMessages.map((message, index) => <MessageCard key={`${message.message_id}-${index}`} message={message} pinPending={pinPending === message.message_id} onTogglePin={(item) => void togglePin(item)} />)}</div>
            {streamError ? <div className="chat-stream-error" role="alert">{streamError}</div> : null}
            <form className="chat-composer" onSubmit={sendMessage}><label className="visually-hidden" htmlFor="video-chat-input">Ask about this video</label><textarea id="video-chat-input" maxLength={8000} rows={3} value={draft} disabled={!canChat || streaming} placeholder={canChat ? "Ask a question about this video…" : "Chat is unavailable while processing"} onChange={(event) => setDraft(event.target.value)} /><div>{streaming ? <Button className="danger-button" onClick={() => void stop()}>Stop generating</Button> : <Button variant="primary" type="submit" disabled={!canChat || !draft.trim()}>Send</Button>}</div></form>
          </>}
        </Panel>
        <Panel className="pins-panel" aria-label="Pinned answers"><div className="video-section__heading"><h2>Pinned answers</h2></div>{pins.length === 0 ? <p className="muted-text">Pin an assistant answer to keep it close.</p> : <ol>{pins.map((pin) => <li key={pin.pin_id}><p>{pin.content}</p><Link to={videoPath(video.video_id, pin.conversation_id)}>Open source conversation</Link><Button variant="ghost" onClick={() => void togglePin({ message_id: pin.message_id, role: "assistant", content: pin.content, tool_trace: null, created_at: pin.pinned_at, pinned: true })}>Unpin</Button></li>)}</ol>}</Panel>
      </div>
      <Dialog open={deleting !== null} title="Delete this conversation?" onClose={() => setDeleting(null)} actions={<><Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button><Button className="danger-button" pending={deletePending} onClick={() => void confirmDelete()}>{deletePending ? "Deleting…" : "Delete permanently"}</Button></>}><p>This permanently removes the conversation, all of its messages, and every answer pinned from it. This cannot be undone.</p></Dialog>
    </section>
  );
}
