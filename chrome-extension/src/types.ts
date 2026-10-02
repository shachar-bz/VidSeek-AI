// Shared browser discovery and companion API contracts.
export type MediaKind = "direct" | "hls" | "dash";

export interface MediaCandidate {
  kind: MediaKind;
  url: string;
  mime_type: string;
  source: string;
  headers?: Record<string, string>;
  /** Read from a captured playlist, only to tell the video picker's choices apart. */
  duration_seconds?: number;
  /** The tallest rendition a captured master playlist offers, for the same picker. */
  max_height?: number;
  /** How much of a captured stream the player fetched during the capture, for the picker. */
  played_seconds?: number;
}

export interface CaptionCandidate {
  url?: string;
  text?: string;
  format: string;
  language?: string;
  is_active: boolean;
  is_manual: boolean;
  is_visible_transcript: boolean;
}

export interface DiscoveryResult {
  frame_url?: string;
  selected_media_id?: string;
  media_duration_seconds?: number;
  /** The page's own player was playing this video when the page was inspected. */
  media_playing?: boolean;
  structured_candidates?: string[];
  videos?: DiscoveryResult[];
  page_url: string;
  page_title: string;
  preferred_language?: string;
  drm_detected: boolean;
  media_candidates: MediaCandidate[];
  caption_candidates: CaptionCandidate[];
}

export interface BrowserCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure: boolean;
  http_only: boolean;
  expiration_date?: number;
}

export interface BrowserContext {
  cookies: BrowserCookie[];
  headers: Record<string, string>;
  user_agent: string;
}

export interface VideoJob {
  job_id: string;
  status: string;
  phase: string;
  progress: number;
  message: string;
  acquisition_mode: string;
  video_path?: string;
  transcript_text_path?: string;
  transcript_json_path?: string;
  transcript_source?: string;
  comments_path?: string;
  /** The video's blob name in the storage container, absent until it is uploaded. */
  video_storage_key?: string;
  /** The video row the job produced, absent until the pipeline has written it. */
  video_id?: string;
  error_code?: string;
  can_capture: boolean;
}

export interface TrackedJob {
  jobId: string;
  token: string;
  grantedOrigins: string[];
  downloadId?: number;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name?: string | null;
}

export interface AuthSession {
  token: string;
  user: AuthUser;
}

export type ExtensionMessage =
  | { type: "TRACK_JOB"; tracker: TrackedJob }
  | { type: "START_BROWSER_DOWNLOAD"; tracker: TrackedJob; url: string; filename: string }
  | { type: "GET_TRACKED_JOB" }
  | { type: "CANCEL_TRACKED_JOB" }
  // jobId is omitted for a pre-download DRM verification: no job exists yet to retry.
  | { type: "START_CAPTURE"; tabId: number; jobId?: string }
  | { type: "STOP_CAPTURE" };

/** What `STOP_CAPTURE` hands back: a DRM verdict, or the media requests it captured. */
export interface StopCaptureResult {
  drm_detected: boolean;
  reason?: string;
  candidates: MediaCandidate[];
  caption_candidates?: CaptionCandidate[];
  tab_id?: number;
}


/**
 * The video a signed-in user last scanned, kept in `chrome.storage.local` so the processing
 * screen and then the chat come back after the panel closes, the user signs out, or the
 * browser restarts. The job itself runs in the companion either way.
 */
export interface ScannedVideo {
  userId: string;
  jobId: string;
  /** The companion session token the job is polled with. */
  jobToken: string;
  title: string;
  pageUrl: string;
  videoId?: string;
}

/** How far along a video is. Mirrors `ReadinessStage` in backend/schemas/readiness.py. */
export type ReadinessStage =
  | "downloading"
  | "transcribing"
  | "understanding"
  | "ready"
  | "failed";

/** Whether the agent has anything to retrieve yet. Mirrors `ReadinessStage.allows_chat`. */
export function allowsChat(stage: ReadinessStage): boolean {
  return stage === "ready";
}

export type VisualStatus = "pending" | "indexing" | "ready" | "failed" | "skipped";

export interface VideoInsights {
  summary: string;
  takeaways: string[];
  suggested_questions: string[];
}

export interface VideoDetail {
  video_id: string;
  title: string;
  custom_title?: string | null;
  original_title: string;
  source_site: string;
  source_url: string;
  duration_seconds?: number | null;
  tags: string[];
  added_at: string;
  stage: ReadinessStage;
  transcript_source?: string | null;
  transcript_language?: string | null;
  transcript_timing_fidelity?: string | null;
  insights?: VideoInsights | null;
  conversation_count: number;
  visual_status?: VisualStatus | null;
}

export interface ToolCallTrace {
  call_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  summary?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  /** What the call is doing, in words, for the line under a pending answer. Live only. */
  activity?: string | null;
}

export interface ConversationMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  tool_trace?: ToolCallTrace[] | null;
  created_at: string;
  pinned: boolean;
}

export interface ConversationSummary {
  conversation_id: string;
  video_id: string;
  title?: string | null;
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
  title?: string | null;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

export interface SendMessageRequest {
  content: string;
  current_time_seconds?: number | null;
  player_paused?: boolean | null;
}

/** The SSE event name every answer payload arrives under. Mirrors `STREAM_EVENT_NAME`. */
export const STREAM_EVENT_NAME = "message";

/** One event on an answer's stream. Mirrors `StreamEvent` in backend/schemas/conversations.py. */
export type StreamEvent =
  | { type: "message_start"; user_message_id: string; message_id: string }
  | { type: "token"; text: string }
  | { type: "tool_call"; call: ToolCallTrace }
  | { type: "tool_result"; call: ToolCallTrace }
  | { type: "message_complete"; message: ConversationMessage }
  | { type: "stopped"; message: ConversationMessage }
  | { type: "error"; message: string };
