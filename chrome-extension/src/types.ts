export type MediaKind = "direct" | "hls" | "dash";

export interface MediaCandidate {
  kind: MediaKind;
  url: string;
  mime_type: string;
  source: string;
  headers?: Record<string, string>;
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
}

