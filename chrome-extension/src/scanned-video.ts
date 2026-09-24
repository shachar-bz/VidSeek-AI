// Remembers each user's last scanned video across panel closes, sign-outs and restarts.
import type { ScannedVideo } from "./types";

// Local rather than session storage: a scan takes minutes and its chat is worth coming back
// to after the browser restarts. Keyed by user, so signing in as someone else never shows
// another account's video, and signing back in picks up where that user left off.
const SCANNED_VIDEOS_KEY = "vidseekScannedVideos";

type ScannedVideosByUser = Record<string, ScannedVideo>;

async function readAll(): Promise<ScannedVideosByUser> {
  const stored = await chrome.storage.local.get(SCANNED_VIDEOS_KEY);
  return (stored[SCANNED_VIDEOS_KEY] as ScannedVideosByUser | undefined) ?? {};
}

async function writeAll(videos: ScannedVideosByUser): Promise<void> {
  await chrome.storage.local.set({ [SCANNED_VIDEOS_KEY]: videos });
}

export async function readScannedVideo(
  userId: string,
): Promise<ScannedVideo | undefined> {
  return (await readAll())[userId];
}

export async function writeScannedVideo(video: ScannedVideo): Promise<void> {
  const videos = await readAll();
  videos[video.userId] = video;
  await writeAll(videos);
}

export async function clearScannedVideo(userId: string): Promise<void> {
  const videos = await readAll();
  delete videos[userId];
  await writeAll(videos);
}

/**
 * Records the video a job produced on whichever user's scan that job is. Called by both the
 * panel and the background worker, so the id is kept even when the job finishes while the
 * panel is closed and the companion later forgets the job.
 */
export async function recordScannedVideoId(
  jobId: string,
  videoId: string,
): Promise<void> {
  const videos = await readAll();
  const scan = Object.values(videos).find((video) => video.jobId === jobId);
  if (!scan || scan.videoId === videoId) return;
  scan.videoId = videoId;
  await writeAll(videos);
}
