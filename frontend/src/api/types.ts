// The wire contract, mirroring backend/schemas/ field for field. Nothing else defines it.
//
// Every name here has a counterpart in a Pydantic model, and the field names are the
// snake_case ones the API actually sends — they are deliberately not camelCased on the way
// in, because a rename in one place and not the other is the one mistake neither TypeScript
// nor Pydantic can catch. `backend/tests/test_website_schemas.py` pins the string values of
// every enum below for the same reason.
//
// Which module each block mirrors:
//   ReadinessStage            backend/schemas/readiness.py
//   Library*                  backend/schemas/library.py
//   Video*, Playback*, Pin*   backend/schemas/videos.py
//   Conversation*, Stream*    backend/schemas/conversations.py
//   Account*, Session*        backend/schemas/account.py
//   Auth*                     backend/schemas/auth.py

// --- readiness -------------------------------------------------------------------------

/** The five states a video is shown in. `failed` sits outside the sequence. */
export type ReadinessStage =
  | "downloading"
  | "transcribing"
  | "understanding"
  | "ready"
  | "failed";

/** Whether the agent has anything to retrieve. Mirrors `ReadinessStage.allows_chat`. */
export function allowsChat(stage: ReadinessStage): boolean {
  return stage === "ready";
}

/** Whether the player and transcript exist. Mirrors `ReadinessStage.allows_browsing`. */
export function allowsBrowsing(stage: ReadinessStage): boolean {
  return stage === "understanding" || stage === "ready";
}

// --- auth ------------------------------------------------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface SignUpRequest {
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// --- account ---------------------------------------------------------------------------

export type Surface = "website" | "extension";

export interface SessionSummary {
  session_id: string;
  surface: Surface;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  /** The session this page is being read through; revoking it signs the page out. */
  current: boolean;
}

export interface SessionList {
  sessions: SessionSummary[];
}

export interface UpdateAccountRequest {
  display_name: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface DeleteAccountRequest {
  password: string;
}

// --- library ---------------------------------------------------------------------------

export type LibrarySort = "added_at" | "duration";
export type SortDirection = "asc" | "desc";

/**
 * One row of the library page.
 *
 * `video_id` is null for the whole of `downloading` and `transcribing`: there is no video
 * row yet, so the row is not clickable and everything derived from the video is empty.
 * `job_id` is null once a job has been pruned, or for a video recorded before jobs were
 * persisted. At least one of the two is always set.
 */
export interface LibraryVideo {
  video_id: string | null;
  job_id: string | null;
  /** The effective title: the custom one when set, the captured one otherwise. */
  title: string;
  custom_title: string | null;
  source_site: string;
  source: string;
  source_url: string;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  tags: string[];
  added_at: string | null;
  stage: ReadinessStage;
  progress: number;
  status_message: string;
  error_code: string | null;
  conversation_count: number;
}

export interface LibraryPage {
  videos: LibraryVideo[];
  /** Every row matching the filters, not the rows returned. */
  total: number;
  limit: number;
  offset: number;
}

/** Every filter, sort and page control `GET /v1/library` accepts, all optional. */
export interface LibraryQuery {
  search?: string;
  /** Narrowing: a row must carry every tag listed, not any of them. */
  tags?: string[];
  source_site?: string;
  stage?: ReadinessStage;
  added_after?: string;
  added_before?: string;
  has_conversations?: boolean;
  sort?: LibrarySort;
  direction?: SortDirection;
  limit?: number;
  offset?: number;
}

/**
 * A rename, a re-tag, or both.
 *
 * An omitted field means "leave this alone". `custom_title: null` sent explicitly is how a
 * rename is cleared back to the video's own title, so the two cases must not be conflated
 * by a client that strips nulls before sending.
 */
export interface UpdateLibraryLinkRequest {
  custom_title?: string | null;
  tags?: string[];
}

export interface TagList {
  tags: string[];
}

/** One update on the library's live channel; applied to a row field by field. */
export interface LibraryProgressEvent {
  job_id: string;
  /** Appears mid-stream, the moment the video row is written. */
  video_id: string | null;
  stage: ReadinessStage;
  progress: number;
  status_message: string;
  error_code: string | null;
}

// --- video -----------------------------------------------------------------------------

export interface VideoInsights {
  summary: string;
  takeaways: string[];
  /** Each opens a new conversation pre-filled with exactly this text. */
  suggested_questions: string[];
}

/**
 * How far a video's visual index is. Mirrors `VisualStatus`. Separate from the readiness
 * stage: a video is ready to chat about before its index finishes, and one whose index failed
 * or was skipped still answers everything its transcript can.
 */
export type VisualStatus = "pending" | "indexing" | "ready" | "failed" | "skipped";

export interface VideoDetail {
  video_id: string;
  title: string;
  custom_title: string | null;
  original_title: string;
  source_site: string;
  source_url: string;
  duration_seconds: number | null;
  tags: string[];
  added_at: string;
  stage: ReadinessStage;
  transcript_source: string | null;
  transcript_language: string | null;
  /** "word" or "caption". What a click-to-seek is worth on this video. */
  transcript_timing_fidelity: string | null;
  /** Null for every video before `ready`; not an error. */
  insights: VideoInsights | null;
  conversation_count: number;
  /** Whether questions about what the video shows can search all of it yet. */
  visual_status: VisualStatus | null;
}

/**
 * A short-lived signed link to the video's bytes.
 *
 * The URL carries a signature and is a credential for one blob: it must not be logged,
 * persisted, or put anywhere the user can copy it out of. Refresh it before `expires_at`
 * rather than letting a long video stop playing.
 */
export interface PlaybackUrl {
  url: string;
  expires_at: string;
  expires_in_seconds: number;
}

/** How long before expiry to fetch a new playback URL, mirroring the backend constant. */
export const PLAYBACK_URL_REFRESH_MARGIN_SECONDS = 300;

export interface TranscriptLine {
  index: number;
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface VideoTranscript {
  video_id: string;
  timing_fidelity: string | null;
  lines: TranscriptLine[];
}

export interface ChapterOutlineEntry {
  chapter_id: string;
  chapter_index: number;
  title: string;
  summary: string;
  start_seconds: number;
  end_seconds: number;
}

export interface VideoOutlineResponse {
  video_id: string;
  /** Empty for every video before `ready`. Not an error. */
  chapters: ChapterOutlineEntry[];
}

export interface PinnedAnswer {
  pin_id: string;
  message_id: string;
  conversation_id: string;
  content: string;
  /** When the pinned message itself was sent, as opposed to when it was pinned. */
  message_created_at: string;
  pinned_at: string;
}

export interface PinnedAnswerList {
  video_id: string;
  pins: PinnedAnswer[];
}

export interface PinAnswerRequest {
  message_id: string;
}

// --- conversations ---------------------------------------------------------------------

export type MessageRole = "user" | "assistant";

/**
 * One retrieval the agent performed.
 *
 * `finished_at` is null while the call is still running, which is how a live trace shows
 * one in progress. `summary` describes what came back without carrying it.
 */
export interface ToolCallTrace {
  call_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  summary: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  /** What the call is doing, in words, for the line under a pending answer. Live only. */
  activity?: string | null;
}

export interface ConversationMessage {
  message_id: string;
  role: MessageRole;
  content: string;
  /** Null on a user message, and on an assistant message answered without a tool. */
  tool_trace: ToolCallTrace[] | null;
  created_at: string;
  pinned: boolean;
}

export interface ConversationSummary {
  conversation_id: string;
  video_id: string;
  /** Null until the first exchange generates one. */
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationList {
  video_id: string;
  conversations: ConversationSummary[];
}

export interface ConversationDetail {
  conversation_id: string;
  video_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

export interface CreateConversationRequest {
  /** What a suggested question pre-fills. Creating the thread does not send it. */
  first_message?: string;
}

export interface RenameConversationRequest {
  title: string;
}

export interface SendMessageRequest {
  content: string;
  /**
   * Where the player was when the question was sent: what "this" and "on screen now" refer
   * to. Omitted when there is no player position to give.
   */
  current_time_seconds?: number | null;
  /**
   * Whether the player was paused there: paused, the position is the very frame asked about;
   * playing, what was asked about may be a few seconds earlier. Sent with the position.
   */
  player_paused?: boolean | null;
}

// --- the answer stream -----------------------------------------------------------------

export type StreamEventType =
  | "message_start"
  | "token"
  | "tool_call"
  | "tool_result"
  | "message_complete"
  | "stopped"
  | "error";

/** Every payload arrives under this server-sent event name; `type` discriminates. */
export const STREAM_EVENT_NAME = "message";

export interface MessageStartEvent {
  type: "message_start";
  user_message_id: string;
  message_id: string;
}

/** One fragment, to append — not the answer so far. */
export interface TokenEvent {
  type: "token";
  text: string;
}

export interface ToolCallEvent {
  type: "tool_call";
  call: ToolCallTrace;
}

export interface ToolResultEvent {
  type: "tool_result";
  call: ToolCallTrace;
}

/** The last event on a successful stream; carries the message as it was persisted. */
export interface MessageCompleteEvent {
  type: "message_complete";
  message: ConversationMessage;
}

/** Stopping loses the generation, not the conversation: the partial answer is kept. */
export interface StoppedEvent {
  type: "stopped";
  message: ConversationMessage;
}

/** Arrives on the stream rather than as a status, because the response already began. */
export interface ErrorEvent {
  type: "error";
  message: string;
}

export type StreamEvent =
  | MessageStartEvent
  | TokenEvent
  | ToolCallEvent
  | ToolResultEvent
  | MessageCompleteEvent
  | StoppedEvent
  | ErrorEvent;
