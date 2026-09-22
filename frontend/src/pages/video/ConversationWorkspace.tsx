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
import { splitMessageCitations } from "./format";
import { beginGeneration, applyStreamEvent, endIncompleteStream, type LiveGeneration } from "./streamState";
import { ToolTrace } from "./ToolTrace";

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

export function starterQuestionsForVideo(video: Pick<VideoDetail, "title" | "insights">): string[] {
  const generated = video.insights?.suggested_questions ?? [];
  const fallbacks = [
    `What are the main ideas in “${video.title}”?`,
    "What are the most important details to remember?",
    "Can you explain the key concepts with examples?"
  ];
  return Array.from(new Set([...generated, ...fallbacks])).slice(0, 3);
}

export function chatUnavailableMessage(stage: VideoDetail["stage"]): string | null {
  if (allowsChat(stage)) return null;
  if (stage === "failed") return "Chat is unavailable because processing failed.";
  return `${stage.charAt(0).toUpperCase() + stage.slice(1)} is in progress. Questions become available when processing completes.`;
}

export function AnswerText({
  content,
  approximate,
  onSeek
}: {
  content: string;
  approximate: boolean;
  onSeek(seconds: number): void;
}) {
  return (
    <>
      {splitMessageCitations(content).map((segment, index) => segment.kind === "citation" ? (
        <button
          key={index}
          className={approximate ? "chat-message__timestamp chat-message__timestamp--approximate" : "chat-message__timestamp"}
          type="button"
          title={approximate ? "Seek using this approximate timestamp" : "Seek to this timestamp"}
          onClick={() => onSeek(segment.seconds)}
        >
          {segment.text}
        </button>
      ) : <span key={index}>{segment.text}</span>)}
    </>
  );
}

function MessageCard({
  message,
  pinPending,
  pinDisabled,
  approximate,
  onSeek,
  onTogglePin
}: {
  message: ConversationMessage;
  pinPending: boolean;
  pinDisabled: boolean;
  approximate: boolean;
  onSeek(seconds: number): void;
  onTogglePin(message: ConversationMessage): void;
}) {
  const assistant = message.role === "assistant";
  return (
    <article className={`chat-message chat-message--${message.role}`}>
      <header><span>{assistant ? "VidSeek" : "You"}</span>{assistant ? <Button variant="ghost" pending={pinPending} disabled={pinDisabled} onClick={() => onTogglePin(message)}>{message.pinned ? "Unpin" : "Pin answer"}</Button> : null}</header>
      <div className="chat-message__content">{!message.content ? (assistant ? "Waiting for an answer…" : "") : assistant ? <AnswerText content={message.content} approximate={approximate} onSeek={onSeek} /> : message.content}</div>
      {assistant ? <ToolTrace calls={message.tool_trace} /> : null}
    </article>
  );
}

export function ConversationWorkspace({
  video,
  approximate,
  onSeek
}: {
  video: VideoDetail;
  approximate: boolean;
  onSeek(seconds: number): void;
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
  const draftConversationRef = useRef<string | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
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
        if (!controller.signal.aborted) setWorkspaceError(featureFailureMessage(caught, "Chats and pins could not be loaded."));
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
    setDetail(null);
    if (draftConversationRef.current !== selectedId) {
      draftConversationRef.current = selectedId;
      setDraft("");
    }
    if (!selectedId) {
      setRenameDraft("");
      return;
    }
    const controller = new AbortController();
    setWorkspaceError(null);
    getConversation(selectedId, controller.signal)
      .then((response) => {
        if (response.video_id !== video.video_id) throw new Error("This chat belongs to another video.");
        setDetail(response);
        setRenameDraft(response.title ?? "");
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setWorkspaceError(featureFailureMessage(caught, "This chat could not be loaded."));
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
      draftConversationRef.current = created.conversation_id;
      setDraft(prefill);
      navigate(videoPath(video.video_id, created.conversation_id));
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "A new chat could not be created."));
    } finally {
      setCreating(false);
    }
  }, [canChat, navigate, video.video_id]);

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
          try {
            await loadConversationList();
            const refreshed = await getConversation(selectedId);
            if (generationRef.current === generation) {
              setDetail(refreshed);
              setRenameDraft(refreshed.title ?? "");
            }
          } catch (caught) {
            if (generationRef.current === generation) {
              setWorkspaceError(featureFailureMessage(caught, "The answer was saved, but chat details could not be refreshed."));
            }
          }
        } else if (next.terminal === "error") {
          terminal = true;
          const message = streamEvent.type === "error"
            ? `Agent not available yet. ${next.error ?? "The answer could not be completed."}`
            : next.error;
          setStreamError(message);
          updateLive({ ...next, error: message });
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
      setWorkspaceError(featureFailureMessage(caught, "The chat could not be renamed."));
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
      setWorkspaceError(featureFailureMessage(caught, "The chat could not be deleted."));
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
  const starterQuestions = useMemo(() => starterQuestionsForVideo(video), [video]);

  function chooseStarterQuestion(question: string) {
    draftConversationRef.current = selectedId;
    setDraft(question);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  return (
    <section className="conversation-feature" aria-labelledby="conversation-heading">
      {unavailable ? <div className="inline-notice" role="status">{unavailable}</div> : null}
      {workspaceError ? <div className="inline-notice" role="alert">{workspaceError}</div> : null}
      <div className="conversation-grid">
        <Panel className="chat-panel">
          <header className="chat-panel__header"><h2 id="conversation-heading">Ask VidSeek</h2><p>Get answers, summaries, and insights from this video.</p></header>
          {!selectedId ? <EmptyState title="Start a new chat" description="Ask VidSeek anything about this video." action={<Button variant="primary" pending={creating} disabled={!canChat} onClick={() => void startNewConversation()}>{creating ? "Creating…" : "New chat"}</Button>} /> : !detail ? <p className="muted-text">Loading chat…</p> : <>
            <form className="conversation-title-form" onSubmit={saveRename}><input aria-label="Chat title" maxLength={200} value={renameDraft} placeholder="New chat" onChange={(event) => setRenameDraft(event.target.value)} /><Button variant="ghost" pending={renaming} type="submit" disabled={!renameDraft.trim()}>Rename</Button>{selectedSummary ? <Button className="danger-button" variant="ghost" onClick={() => setDeleting(selectedSummary)}>Delete</Button> : null}</form>
            <div className="chat-history" aria-live="polite">{renderedMessages.length === 0 ? <section className="chat-starters" aria-labelledby="chat-starters-heading"><h3 id="chat-starters-heading">Try asking</h3><div>{starterQuestions.map((question) => <button type="button" key={question} onClick={() => chooseStarterQuestion(question)}>{question}</button>)}</div></section> : renderedMessages.map((message, index) => <MessageCard key={`${message.message_id}-${index}`} message={message} pinPending={pinPending === message.message_id} pinDisabled={message.message_id.startsWith("pending-") || (streaming && message.message_id === live?.assistantMessage.message_id)} approximate={approximate} onSeek={onSeek} onTogglePin={(item) => void togglePin(item)} />)}</div>
            {streamError ? <div className="chat-stream-error" role="alert">{streamError}</div> : null}
            <form className="chat-composer" onSubmit={sendMessage}><label className="visually-hidden" htmlFor="video-chat-input">Ask about this video</label><textarea ref={composerRef} id="video-chat-input" maxLength={8000} rows={2} value={draft} disabled={!canChat || streaming} placeholder={canChat ? "Ask anything about this video" : "Chat is unavailable while processing"} onChange={(event) => { draftConversationRef.current = selectedId; setDraft(event.target.value); }} /><div>{streaming ? <Button className="danger-button" onClick={() => void stop()}>Stop generating</Button> : <Button variant="primary" type="submit" aria-label="Send message" disabled={!canChat || !draft.trim()}>Send</Button>}</div></form>
          </>}
        </Panel>
        <Panel className="chat-sidebar">
          <Button className="new-chat-button" variant="secondary" pending={creating} disabled={!canChat} onClick={() => void startNewConversation()}><span aria-hidden="true">＋</span>{creating ? "Creating…" : "New chat"}</Button>
          <section className="pins-panel" aria-labelledby="pinned-answers-heading"><div className="chat-sidebar__heading"><h2 id="pinned-answers-heading">Pinned answers</h2></div>{pins.length === 0 ? <p className="muted-text">Pin an answer to keep it close.</p> : <ol>{pins.map((pin) => <li key={pin.pin_id}><p className="chat-message__content"><AnswerText content={pin.content} approximate={approximate} onSeek={onSeek} /></p><Link to={videoPath(video.video_id, pin.conversation_id)}>Open source chat</Link><Button variant="ghost" onClick={() => void togglePin({ message_id: pin.message_id, role: "assistant", content: pin.content, tool_trace: null, created_at: pin.pinned_at, pinned: true })}>Unpin</Button></li>)}</ol>}</section>
          <section className="conversation-list-panel" aria-labelledby="recents-heading"><div className="chat-sidebar__heading"><h2 id="recents-heading">Recents</h2></div>{loading ? <p className="muted-text">Loading chats…</p> : conversations.length === 0 ? <p className="muted-text">No chats yet.</p> : <ol className="conversation-list">{conversations.map((conversation) => <li key={conversation.conversation_id} className={conversation.conversation_id === selectedId ? "conversation-list__item conversation-list__item--active" : "conversation-list__item"}><button type="button" onClick={() => navigate(videoPath(video.video_id, conversation.conversation_id))}><strong>{conversation.title ?? "New chat"}</strong><span>{formatLastUsed(conversation.updated_at)}</span></button><Button variant="ghost" aria-label={`Delete ${conversation.title ?? "chat"}`} onClick={() => setDeleting(conversation)}>×</Button></li>)}</ol>}</section>
        </Panel>
      </div>
      <Dialog open={deleting !== null} title="Delete this chat?" onClose={() => setDeleting(null)} actions={<><Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button><Button className="danger-button" pending={deletePending} onClick={() => void confirmDelete()}>{deletePending ? "Deleting…" : "Delete permanently"}</Button></>}><p>This permanently removes the chat, all of its messages, and every answer pinned from it. This cannot be undone.</p></Dialog>
    </section>
  );
}
