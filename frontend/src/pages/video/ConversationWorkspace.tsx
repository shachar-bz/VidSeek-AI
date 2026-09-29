import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent
} from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

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
  type SendMessageRequest,
  type ToolCallTrace,
  type VideoDetail
} from "../../api/types";
import { getPinnedAnswers, pinAnswer, unpinAnswer } from "../../api/video";
import agentAvatar from "../../assets/vidseek-video-chat-agent-icon.png";
import { Button, Dialog, Panel } from "../../components/ui";
import { videoPath } from "../../routes";
import { featureFailureMessage } from "../shared";
import { splitMessageCitations } from "./format";
import { beginGeneration, applyStreamEvent, endIncompleteStream, type LiveGeneration } from "./streamState";

const CHAT_NAME = /^Chat (\d+)$/;

export function pinnedAnswerPreview(content: string): string {
  const text = content.replace(/\s+/g, " ").trim();
  const characters = Array.from(text);
  return characters.length > 160 ? `${characters.slice(0, 160).join("").trimEnd()}…` : text;
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

function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(date);
}

/** Where the player stood when a message was sent, and whether it was paused there. */
export interface PlayerPosition {
  seconds: number;
  paused: boolean;
}

/**
 * Chats are numbered rather than named by hand: the next one continues the highest
 * `Chat N` this video already has, so a renamed chat never steals a number back.
 */
export function nextChatName(conversations: ConversationSummary[]): string {
  const highest = conversations.reduce((current, conversation) => {
    const match = CHAT_NAME.exec(conversation.title ?? "");
    return match ? Math.max(current, Number(match[1])) : current;
  }, 0);
  return `Chat ${highest + 1}`;
}

export function starterQuestionsForVideo(video: Pick<VideoDetail, "insights">): string[] {
  const generated = video.insights?.suggested_questions ?? [];
  const fallbacks = [
    "What are the main ideas in this video?",
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

function PencilIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m4 20 4.5-1 10-10-3.5-3.5-10 10L4 20Z" /><path d="m13.5 6.5 3.5 3.5" /></svg>; }
function ArrowUpIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></svg>; }
function ChevronIcon({ pointing }: { pointing: "left" | "right" }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d={pointing === "right" ? "m9 5 7 7-7 7" : "m15 5-7 7 7 7"} /></svg>;
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

/** The server's label for the call still running, or the last one; "Thinking" before any. */
export function latestActivity(trace: ToolCallTrace[] | null | undefined): string {
  const running = [...(trace ?? [])].reverse().find((call) => !call.finished_at);
  const call = running ?? trace?.at(-1);
  return call?.activity || "Thinking";
}

function MessageCard({
  message,
  pending,
  pinPending,
  pinDisabled,
  highlighted,
  approximate,
  onSeek,
  onTogglePin
}: {
  message: ConversationMessage;
  /** The answer still being generated, which shows what the agent is doing instead of text. */
  pending: boolean;
  pinPending: boolean;
  pinDisabled: boolean;
  highlighted: boolean;
  approximate: boolean;
  onSeek(seconds: number): void;
  onTogglePin(message: ConversationMessage): void;
}) {
  const assistant = message.role === "assistant";
  const sentAt = formatMessageTime(message.created_at);
  return (
    <article id={`message-${message.message_id}`} tabIndex={-1} className={`chat-message chat-message--${message.role}${highlighted ? " chat-message--highlighted" : ""}`}>
      {assistant ? <img className="chat-message__avatar" src={agentAvatar} alt="VidSeek" /> : null}
      <div className="chat-message__body">
        {assistant && !message.content ? (
          pending ? (
            <div className="chat-message__bubble chat-message__bubble--typing"><span className="chat-typing" /></div>
          ) : (
            <div className="chat-message__bubble chat-message__bubble--empty">No answer was saved for this question.</div>
          )
        ) : (
          <div className="chat-message__bubble">
            <div className="chat-message__content">{assistant ? <AnswerText content={message.content} approximate={approximate} onSeek={onSeek} /> : message.content}</div>
          </div>
        )}
        {pending && assistant ? <p className="chat-message__activity">{latestActivity(message.tool_trace)}…</p> : null}
        <footer className="chat-message__meta">
          {sentAt ? <time dateTime={message.created_at}>{sentAt}</time> : null}
          {assistant ? (
            <button
              className={message.pinned ? "chat-message__pin chat-message__pin--pinned" : "chat-message__pin"}
              type="button"
              disabled={pinDisabled || pinPending}
              aria-label={message.pinned ? "Unpin this answer" : "Pin this answer"}
              onClick={() => onTogglePin(message)}
            >
              {message.pinned ? "Pinned" : "Pin"}
            </button>
          ) : null}
        </footer>
      </div>
    </article>
  );
}

export function ConversationWorkspace({
  video,
  approximate,
  onSeek,
  playerPosition
}: {
  video: VideoDetail;
  approximate: boolean;
  onSeek(seconds: number): void;
  /** The player's position right now and whether it is paused, read when a message is sent; null without a player. */
  playerPosition?(): PlayerPosition | null;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const selectedId = searchParams.get("conversation");
  const selectedMessageId = searchParams.get("message");
  const focusedPinRef = useRef<string | null>(null);
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
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const generationRef = useRef(0);
  const streamControllerRef = useRef<AbortController | null>(null);
  const draftConversationRef = useRef<string | null>(null);
  // A chat this page has just created for the message it is about to send. Selecting it must
  // not reset the panel the way opening a chat does, or it would abort that message's stream.
  const adoptedConversationRef = useRef<string | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const historyRef = useRef<HTMLDivElement | null>(null);
  // Whether the history is scrolled to its end, so new and streaming messages keep it there
  // without pulling a reader back down while they scroll through earlier answers.
  const followHistoryRef = useRef(true);
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
    if (selectedId && adoptedConversationRef.current === selectedId) {
      adoptedConversationRef.current = null;
      return;
    }
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
    if (!selectedId) return;
    const controller = new AbortController();
    setWorkspaceError(null);
    getConversation(selectedId, controller.signal)
      .then((response) => {
        if (response.video_id !== video.video_id) throw new Error("This chat belongs to another video.");
        setDetail(response);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setWorkspaceError(featureFailureMessage(caught, "This chat could not be loaded."));
      });
    return () => controller.abort();
  }, [selectedId, updateLive, video.video_id]);

  /**
   * A new chat is only a blank panel until its first message is sent: nothing is stored for
   * a chat the user opened and left without typing into.
   */
  function openNewChat() {
    if (!canChat) return;
    if (selectedId) navigate(videoPath(video.video_id));
    else setDraft("");
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  /** Stores the new chat the first message is being sent from, and opens it. */
  async function createChatForFirstMessage(): Promise<string | null> {
    setCreating(true);
    setWorkspaceError(null);
    try {
      const created = await createConversation(video.video_id);
      let summary = summaryFromDetail(created);
      try {
        summary = await renameConversation(created.conversation_id, { title: nextChatName(conversations) });
      } catch {
        // The chat exists either way; without its number the backend titles it from the first question.
      }
      setConversations((current) => newestFirst([summary, ...current.filter((item) => item.conversation_id !== summary.conversation_id)]));
      setDetail({ ...created, title: summary.title });
      adoptedConversationRef.current = created.conversation_id;
      draftConversationRef.current = created.conversation_id;
      navigate(videoPath(video.video_id, created.conversation_id));
      return created.conversation_id;
    } catch (caught) {
      setWorkspaceError(featureFailureMessage(caught, "A new chat could not be created."));
      return null;
    } finally {
      setCreating(false);
    }
  }

  function commitLiveToHistory(current: LiveGeneration, terminalMessage?: ConversationMessage) {
    setDetail((existing) => existing ? {
      ...existing,
      messages: [...existing.messages, current.userMessage, terminalMessage ?? current.assistantMessage]
    } : existing);
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!canChat || !draft.trim() || streaming || creating) return;
    const content = draft;
    // Read before the chat is created, so the position is the one the question was asked at.
    const position = playerPosition?.() ?? null;
    const conversationId = selectedId ?? await createChatForFirstMessage();
    if (!conversationId) return;
    if (liveRef.current) commitLiveToHistory(liveRef.current);
    const initial = beginGeneration(content);
    followHistoryRef.current = true;
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
      const input: SendMessageRequest = position !== null && Number.isFinite(position.seconds) && position.seconds >= 0
        ? { content, current_time_seconds: position.seconds, player_paused: position.paused }
        : { content };
      for await (const streamEvent of sendConversationMessage(conversationId, input, controller.signal)) {
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
            const refreshed = await getConversation(conversationId);
            if (generationRef.current === generation) setDetail(refreshed);
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

  function startRename(conversation: ConversationSummary) {
    setRenamingId(conversation.conversation_id);
    setRenameDraft(conversation.title ?? "");
  }

  async function saveRename(event: FormEvent) {
    event.preventDefault();
    const conversationId = renamingId;
    if (!conversationId || !renameDraft.trim()) return;
    setRenaming(true);
    try {
      const renamed = await renameConversation(conversationId, { title: renameDraft.trim() });
      setConversations((current) => newestFirst(current.map((item) => item.conversation_id === renamed.conversation_id ? renamed : item)));
      setDetail((current) => current?.conversation_id === renamed.conversation_id ? { ...current, title: renamed.title, updated_at: renamed.updated_at } : current);
      setRenamingId(null);
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

  const renderedMessages = useMemo(() => [
    ...(detail?.messages ?? []),
    ...(live ? [live.userMessage, live.assistantMessage] : [])
  ], [detail?.messages, live]);
  useEffect(() => {
    followHistoryRef.current = !selectedMessageId;
  }, [selectedId, selectedMessageId]);

  useLayoutEffect(() => {
    if (!selectedMessageId || detail?.conversation_id !== selectedId) return;
    const focusKey = `${location.key}:${selectedId}:${selectedMessageId}`;
    if (focusedPinRef.current === focusKey) return;
    const history = historyRef.current;
    const message = document.getElementById(`message-${selectedMessageId}`);
    if (!history || !message || !history.contains(message)) return;
    followHistoryRef.current = false;
    history.scrollTop += message.getBoundingClientRect().top - history.getBoundingClientRect().top - 16;
    message.focus({ preventScroll: true });
    focusedPinRef.current = focusKey;
  }, [detail, selectedId, selectedMessageId, location.key]);

  useEffect(() => {
    const history = historyRef.current;
    if (history && followHistoryRef.current) history.scrollTop = history.scrollHeight;
  }, [renderedMessages, detail]);

  function trackHistoryScroll() {
    const history = historyRef.current;
    if (history) followHistoryRef.current = history.scrollHeight - history.scrollTop - history.clientHeight < 48;
  }

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
      <div className={drawerOpen ? "conversation-grid" : "conversation-grid conversation-grid--collapsed"}>
        <Panel className="chat-panel">
          <header className="chat-panel__header"><h2 id="conversation-heading">Ask VidSeek</h2><p>Get answers, summaries, and insights from this video.</p></header>
          {selectedId && !detail ? <p className="muted-text">Loading chat…</p> : <>
            <div className="chat-history" ref={historyRef} aria-live="polite" onScroll={trackHistoryScroll}>{renderedMessages.length === 0 ? <section className="chat-starters" aria-labelledby="chat-starters-heading"><h3 id="chat-starters-heading">Try asking</h3><div>{starterQuestions.map((question) => <button type="button" key={question} onClick={() => chooseStarterQuestion(question)}>{question}</button>)}</div></section> : renderedMessages.map((message, index) => <MessageCard key={`${message.message_id}-${index}`} message={message} pending={message === live?.assistantMessage && !live.terminal} highlighted={message.message_id === selectedMessageId} pinPending={pinPending === message.message_id} pinDisabled={message.message_id.startsWith("pending-") || (streaming && message.message_id === live?.assistantMessage.message_id)} approximate={approximate} onSeek={onSeek} onTogglePin={(item) => void togglePin(item)} />)}</div>
            {streamError ? <div className="chat-stream-error" role="alert">{streamError}</div> : null}
            <form className="chat-composer" onSubmit={sendMessage}><label className="visually-hidden" htmlFor="video-chat-input">Ask about this video</label><textarea ref={composerRef} id="video-chat-input" maxLength={8000} rows={2} value={draft} disabled={!canChat || streaming || creating} placeholder={canChat ? "Ask anything about this video" : "Chat is unavailable while processing"} onChange={(event) => { draftConversationRef.current = selectedId; setDraft(event.target.value); }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (canChat && !streaming && !creating && draft.trim()) event.currentTarget.form?.requestSubmit(); } }} /><div>{streaming ? <Button className="danger-button" onClick={() => void stop()}>Stop generating</Button> : <Button variant="primary" type="submit" aria-label="Send message" pending={creating} disabled={!canChat || creating || !draft.trim()}><ArrowUpIcon /></Button>}</div></form>
          </>}
        </Panel>
        <div className="conversation-drawer">
          <button
            className="conversation-drawer__handle"
            type="button"
            aria-expanded={drawerOpen}
            aria-controls="conversation-drawer-panel"
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <ChevronIcon pointing={drawerOpen ? "right" : "left"} />
            <span className="visually-hidden">{drawerOpen ? "Hide chats" : "Show chats"}</span>
          </button>
          <div className="conversation-drawer__panel" id="conversation-drawer-panel" aria-hidden={!drawerOpen}>
            <Panel className="chat-sidebar">
              <Button className="new-chat-button" variant="secondary" disabled={!canChat || creating} onClick={openNewChat}><span aria-hidden="true">＋</span>New chat</Button>
              <section className="conversation-list-panel" aria-labelledby="recents-heading">
                <div className="chat-sidebar__heading"><h2 id="recents-heading">Chats</h2></div>
                {loading ? <p className="muted-text">Loading chats…</p> : conversations.length === 0 ? <p className="muted-text">No chats yet.</p> : (
                  <ol className="conversation-list">
                    {conversations.map((conversation) => {
                      const title = conversation.title ?? "New chat";
                      const active = conversation.conversation_id === selectedId;
                      return (
                        <li key={conversation.conversation_id} className={active ? "conversation-list__item conversation-list__item--active" : "conversation-list__item"}>
                          {renamingId === conversation.conversation_id ? (
                            <form className="conversation-rename-form" onSubmit={saveRename}>
                              <input
                                aria-label={`Rename ${title}`}
                                autoFocus
                                maxLength={200}
                                value={renameDraft}
                                onChange={(event) => setRenameDraft(event.target.value)}
                                onKeyDown={(event) => { if (event.key === "Escape") setRenamingId(null); }}
                              />
                              <Button variant="ghost" type="submit" pending={renaming} disabled={!renameDraft.trim()}>Save</Button>
                            </form>
                          ) : (
                            <>
                              <button type="button" onClick={() => navigate(videoPath(video.video_id, conversation.conversation_id))}>
                                <strong>{title}</strong>
                                <span>{formatLastUsed(conversation.updated_at)}</span>
                              </button>
                              <button className="conversation-list__rename" type="button" aria-label={`Rename ${title}`} onClick={() => startRename(conversation)}><PencilIcon /></button>
                              <Button variant="ghost" aria-label={`Delete ${title}`} onClick={() => setDeleting(conversation)}>×</Button>
                            </>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </section>
              <section className="pins-panel" aria-labelledby="pinned-answers-heading">
                <div className="chat-sidebar__heading"><h2 id="pinned-answers-heading">Pinned answers</h2></div>
                {pins.length === 0 ? <p className="muted-text">Pin an answer to keep it close.</p> : <ol>{pins.map((pin) => <li key={pin.pin_id}><Link className="pinned-answer-preview" to={videoPath(video.video_id, pin.conversation_id, pin.message_id)} aria-label={`Open pinned answer: ${pinnedAnswerPreview(pin.content)}`}>{pinnedAnswerPreview(pin.content)}</Link><Button variant="ghost" onClick={() => void togglePin({ message_id: pin.message_id, role: "assistant", content: pin.content, tool_trace: null, created_at: pin.pinned_at, pinned: true })}>Unpin</Button></li>)}</ol>}
              </section>
            </Panel>
          </div>
        </div>
      </div>
      <Dialog open={deleting !== null} title="Delete this chat?" onClose={() => setDeleting(null)} actions={<><Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button><Button className="danger-button" pending={deletePending} onClick={() => void confirmDelete()}>{deletePending ? "Deleting…" : "Delete permanently"}</Button></>}><p>This permanently removes the chat, all of its messages, and every answer pinned from it. This cannot be undone.</p></Dialog>
    </section>
  );
}
