import { ApiError } from "../api/client";

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
