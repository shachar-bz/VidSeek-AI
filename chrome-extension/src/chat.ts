// The chat view: a conversation with the agent about the video a scan produced.
import {
  applyStreamEvent,
  beginAnswer,
  endAnswer,
  type LiveAnswer,
} from "./answer-stream";
import {
  createConversation,
  getConversation,
  listConversations,
  sendConversationMessage,
  stopConversation,
} from "./api";
import { formatTimestamp, splitAnswerCitations } from "./citations";
import { readPlayerPosition, seekPlayer } from "./tab-player";
import type {
  ConversationDetail,
  ConversationMessage,
  ToolCallTrace,
  VideoDetail,
} from "./types";

const titleElement = document.querySelector<HTMLHeadingElement>("#chat-title")!;
const sourceElement = document.querySelector<HTMLParagraphElement>("#chat-source")!;
const messagesElement = document.querySelector<HTMLDivElement>("#chat-messages")!;
const noticeElement = document.querySelector<HTMLParagraphElement>("#chat-notice")!;
const composerElement = document.querySelector<HTMLFormElement>("#chat-composer")!;
const inputElement = document.querySelector<HTMLTextAreaElement>("#chat-input")!;
const sendButton = document.querySelector<HTMLButtonElement>("#chat-send")!;
const stopButton = document.querySelector<HTMLButtonElement>("#chat-stop")!;
const newChatButton = document.querySelector<HTMLButtonElement>("#chat-new")!;

// Offered beside the video's own suggested questions when it has fewer than three.
const FALLBACK_QUESTIONS = [
  "What are the main ideas in this video?",
  "What are the most important details to remember?",
  "Can you explain the key concepts with examples?",
];

// What each of the agent's tools is doing, in words, for the line under a pending answer.
const TOOL_ACTIVITY: Record<string, string> = {
  get_video_info: "Checking the video's details",
  get_video_outline: "Reading the outline",
  get_chapter_context: "Reading a chapter",
  get_memory_context: "Reading a moment closely",
  memories_semantic_search: "Searching the video",
  investigate_visual: "Looking at what the video shows",
};

interface ChatState {
  userToken: string;
  video: VideoDetail;
  /** Null until the first question of a new chat creates it. */
  conversation: ConversationDetail | null;
  live: LiveAnswer | null;
  controller: AbortController | null;
}

let state: ChatState | undefined;

/** Opens the chat on the video's most recently used conversation, or a fresh one. */
export async function openChat(
  userToken: string,
  video: VideoDetail,
): Promise<void> {
  closeChat();
  const current: ChatState = {
    userToken,
    video,
    conversation: null,
    live: null,
    controller: null,
  };
  state = current;
  titleElement.textContent = video.title;
  sourceElement.textContent = video.source_site;
  messagesElement.replaceChildren(
    element("p", "chat-loading", "Opening your chat…"),
  );
  setComposerMode("loading");
  try {
    const { conversations } = await listConversations(userToken, video.video_id);
    const latest = [...conversations].sort(
      (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
    )[0];
    const conversation = latest
      ? await getConversation(userToken, latest.conversation_id)
      : null;
    if (state !== current) return;
    current.conversation = conversation;
  } catch (error) {
    if (state !== current) return;
    showNotice(`Your earlier chats could not be loaded: ${describe(error)}`);
  }
  render();
  inputElement.focus();
}

/** Leaves the chat. An answer still streaming is abandoned; the companion keeps what it had. */
export function closeChat(): void {
  state?.controller?.abort();
  state = undefined;
  messagesElement.replaceChildren();
  inputElement.value = "";
  showNotice("");
  setComposerMode("idle");
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showNotice(text: string, tone: "error" | "hint" = "error"): void {
  noticeElement.textContent = text;
  noticeElement.dataset.tone = tone;
}

/** Loading has nothing to send to yet; while answering, the next question can be typed. */
function setComposerMode(mode: "loading" | "answering" | "idle"): void {
  inputElement.disabled = mode === "loading";
  sendButton.disabled = mode === "loading";
  sendButton.hidden = mode === "answering";
  stopButton.hidden = mode !== "answering";
  newChatButton.disabled = mode !== "idle";
}

function starterQuestions(video: VideoDetail): string[] {
  const generated = video.insights?.suggested_questions ?? [];
  return [...new Set([...generated, ...FALLBACK_QUESTIONS])].slice(0, 3);
}

/** The first thing a new chat shows: what the video is about, and questions to start with. */
function renderIntro(video: VideoDetail): HTMLElement {
  const intro = element("section", "chat-intro");
  intro.append(element("p", "chat-intro__eyebrow", "Ready when you are"));
  intro.append(
    element(
      "p",
      "chat-intro__summary",
      video.insights?.summary ||
        "Ask anything about this video — what was said, what was shown, or where something happens.",
    ),
  );
  const starters = element("div", "chat-starters");
  for (const question of starterQuestions(video)) {
    const button = element("button", "chat-starter", question);
    button.type = "button";
    button.addEventListener("click", () => void ask(question));
    starters.append(button);
  }
  intro.append(starters);
  return intro;
}

function renderAnswerText(target: HTMLElement, content: string): void {
  const approximate = state?.video.stage === "partial";
  for (const segment of splitAnswerCitations(content)) {
    if (segment.kind === "text") {
      target.append(segment.text);
      continue;
    }
    const citation = element(
      "button",
      approximate ? "chat-citation chat-citation--approximate" : "chat-citation",
      segment.text,
    );
    citation.type = "button";
    citation.title = approximate
      ? "Jump to this approximate moment in the video"
      : "Jump to this moment in the video";
    citation.addEventListener("click", () => void seekTo(segment.seconds));
    target.append(citation);
  }
}

function latestActivity(trace: ToolCallTrace[] | null | undefined): string {
  const running = [...(trace ?? [])].reverse().find((call) => !call.finished_at);
  const call = running ?? trace?.at(-1);
  return (call && TOOL_ACTIVITY[call.tool]) || "Thinking";
}

function renderMessage(message: ConversationMessage, pending: boolean): HTMLElement {
  const article = element("article", `chat-message chat-message--${message.role}`);
  const bubble = element("div", "chat-message__bubble");
  if (message.role === "user") {
    bubble.textContent = message.content;
  } else if (message.content) {
    renderAnswerText(bubble, message.content);
  } else if (pending) {
    bubble.classList.add("chat-message__bubble--typing");
    bubble.append(element("span", "chat-typing", ""));
  } else {
    bubble.classList.add("chat-message__bubble--empty");
    bubble.textContent = "No answer was saved for this question.";
  }
  article.append(bubble);
  if (pending && message.role === "assistant") {
    article.append(
      element("p", "chat-message__activity", `${latestActivity(message.tool_trace)}…`),
    );
  }
  return article;
}

let liveNodes: HTMLElement[] = [];

function nearBottom(): boolean {
  return (
    messagesElement.scrollHeight -
      messagesElement.scrollTop -
      messagesElement.clientHeight <
    48
  );
}

/** Redraws the whole conversation: on open, on a new chat, and when an answer settles. */
function render(): void {
  if (!state) return;
  const messages = state.conversation?.messages ?? [];
  messagesElement.replaceChildren();
  liveNodes = [];
  if (!messages.length && !state.live)
    messagesElement.append(renderIntro(state.video));
  for (const message of messages)
    messagesElement.append(renderMessage(message, false));
  renderLive(true);
  setComposerMode(state.live ? "answering" : "idle");
}

/** Redraws only the question and reply still streaming, so a token costs one bubble. */
function renderLive(scroll = nearBottom()): void {
  for (const node of liveNodes) node.remove();
  liveNodes = [];
  if (state?.live) {
    liveNodes = [
      renderMessage(state.live.question, false),
      renderMessage(state.live.reply, !state.live.outcome),
    ];
    messagesElement.append(...liveNodes);
  }
  if (scroll) messagesElement.scrollTop = messagesElement.scrollHeight;
}

async function ask(content: string): Promise<void> {
  const current = state;
  const question = content.trim();
  if (!current || current.live || !question) return;
  showNotice("");
  const intro = messagesElement.querySelector(".chat-intro");
  intro?.remove();
  current.live = beginAnswer(question);
  const controller = new AbortController();
  current.controller = controller;
  inputElement.value = "";
  resizeInput();
  renderLive(true);
  setComposerMode("answering");

  try {
    current.conversation ??= await createConversation(
      current.userToken,
      current.video.video_id,
    );
    const position = await readPlayerPosition(current.video.source_url);
    const events = sendConversationMessage(
      current.userToken,
      current.conversation.conversation_id,
      {
        content: question,
        current_time_seconds: position?.seconds ?? null,
        player_paused: position?.paused ?? null,
      },
      controller.signal,
    );
    for await (const event of events) {
      if (state !== current) return;
      current.live = applyStreamEvent(current.live, event);
      renderLive();
      if (current.live.outcome) break;
    }
    current.live = endAnswer(current.live);
  } catch (error) {
    if (state !== current || controller.signal.aborted) return;
    current.live = { ...current.live, outcome: "error", error: describe(error) };
  }
  settle(current);
}

/** Folds a finished answer into the conversation, keeping whatever the companion stored. */
function settle(current: ChatState): void {
  const live = current.live;
  current.live = null;
  current.controller = null;
  if (!live) return;
  if (live.started && current.conversation) {
    current.conversation.messages.push(live.question, live.reply);
  } else if (live.outcome === "error") {
    // Nothing reached the companion, so the question goes back in the box to retry.
    inputElement.value = live.question.content;
    resizeInput();
  }
  render();
  if (live.outcome === "error")
    showNotice(live.error ?? "The answer could not be finished.");
  inputElement.focus();
}

async function seekTo(seconds: number): Promise<void> {
  if (!state) return;
  const moved = await seekPlayer(state.video.source_url, seconds);
  showNotice(
    moved
      ? ""
      : `Open this video's tab and click the VidSeek AI icon to jump to ${formatTimestamp(seconds)}.`,
    "hint",
  );
}

function resizeInput(): void {
  // Empty, the box goes back to its one-row size rather than keeping a measured height.
  if (!inputElement.value) {
    inputElement.style.height = "";
    return;
  }
  inputElement.style.height = "auto";
  inputElement.style.height = `${Math.min(inputElement.scrollHeight, 132)}px`;
}

composerElement.addEventListener("submit", (event) => {
  event.preventDefault();
  void ask(inputElement.value);
});

inputElement.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  composerElement.requestSubmit();
});

inputElement.addEventListener("input", resizeInput);

stopButton.addEventListener("click", () => {
  const conversation = state?.conversation;
  if (!state?.live || !conversation) return;
  stopButton.disabled = true;
  void stopConversation(state.userToken, conversation.conversation_id)
    .catch((error: unknown) => showNotice(`Could not stop: ${describe(error)}`))
    .finally(() => {
      stopButton.disabled = false;
    });
});

newChatButton.addEventListener("click", () => {
  if (!state || state.live) return;
  state.conversation = null;
  showNotice("");
  render();
  inputElement.focus();
});
