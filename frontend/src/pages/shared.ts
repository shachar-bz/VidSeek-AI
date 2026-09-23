import { ApiError } from "../api/client";

/**
 * The platform a video came from, as people call it: YouTube, Coursera, Vimeo. `source` is
 * how the companion acquired it; a file the browser downloaded has no platform to name.
 */
export function sourceLabel(video: { source_site: string; source?: string }): string {
  if (video.source === "youtube_pipeline" || video.source_site.includes("youtube")) return "YouTube";
  if (video.source_site.includes("drive.google")) return "Google Drive";
  if (video.source_site.includes("vimeo")) return "Vimeo";
  if (video.source === "browser_download" || video.source === "captured_request") return "Upload";
  const host = video.source_site.replace(/^www\./, "");
  const service = host.split(".").at(0) ?? "";
  return service ? service.replace(/^./, (letter) => letter.toUpperCase()) : "Upload";
}

export function featureFailureMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return "A VidSeek dependency is temporarily unavailable. Please try again later.";
    }
    if (error.status === 409) return error.message || "That change conflicts with newer data.";
    if (error.message) return error.message;
  }
  if (error instanceof TypeError) {
    return "We couldn’t reach VidSeek. Check your connection and try again.";
  }
  return fallback;
}
