import { request } from "./client";
import type {
  PinAnswerRequest,
  PinnedAnswer,
  PinnedAnswerList,
  PlaybackUrl,
  VideoDetail,
  VideoOutlineResponse,
  VideoTranscript
} from "./types";

function videoResource(videoId: string, suffix = ""): string {
  return `/v1/videos/${encodeURIComponent(videoId)}${suffix}`;
}

export function getVideo(videoId: string, signal?: AbortSignal): Promise<VideoDetail> {
  return request<VideoDetail>(videoResource(videoId), { signal });
}

export function getPlaybackUrl(videoId: string, signal?: AbortSignal): Promise<PlaybackUrl> {
  return request<PlaybackUrl>(videoResource(videoId, "/playback"), { signal });
}

export function getVideoTranscript(
  videoId: string,
  signal?: AbortSignal
): Promise<VideoTranscript> {
  return request<VideoTranscript>(videoResource(videoId, "/transcript"), { signal });
}

export function getVideoOutline(
  videoId: string,
  signal?: AbortSignal
): Promise<VideoOutlineResponse> {
  return request<VideoOutlineResponse>(videoResource(videoId, "/outline"), { signal });
}

export function getPinnedAnswers(
  videoId: string,
  signal?: AbortSignal
): Promise<PinnedAnswerList> {
  return request<PinnedAnswerList>(videoResource(videoId, "/pins"), { signal });
}

export function pinAnswer(videoId: string, answer: PinAnswerRequest): Promise<PinnedAnswer> {
  return request<PinnedAnswer>(videoResource(videoId, "/pins"), {
    method: "POST",
    body: answer
  });
}

export function unpinAnswer(videoId: string, messageId: string): Promise<void> {
  return request<void>(
    videoResource(videoId, `/pins/${encodeURIComponent(messageId)}`),
    { method: "DELETE" }
  );
}
