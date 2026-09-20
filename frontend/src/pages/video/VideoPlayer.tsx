import { useCallback, useEffect, useRef, useState } from "react";

import { getPlaybackUrl } from "../../api/video";
import {
  PLAYBACK_URL_REFRESH_MARGIN_SECONDS,
  type PlaybackUrl
} from "../../api/types";
import { Button, LoadingState, Panel } from "../../components/ui";
import { featureFailureMessage } from "../shared";

const MINIMUM_REFRESH_DELAY_MS = 1_000;

export function playbackRefreshDelay(playback: PlaybackUrl, now = Date.now()): number {
  const expiresAt = Date.parse(playback.expires_at);
  const lifetimeMs = Math.max(0, playback.expires_in_seconds * 1_000);
  const timeUntilExpiry = Number.isNaN(expiresAt) ? lifetimeMs : Math.max(0, expiresAt - now);
  const preferred = timeUntilExpiry - PLAYBACK_URL_REFRESH_MARGIN_SECONDS * 1_000;
  if (preferred > MINIMUM_REFRESH_DELAY_MS) return preferred;
  return Math.max(MINIMUM_REFRESH_DELAY_MS, Math.floor(timeUntilExpiry / 2));
}

interface PlaybackIntent {
  position: number;
  playing: boolean;
}

export interface VideoPlayerProps {
  videoId: string;
  available: boolean;
  title: string;
  onTimeChange(seconds: number): void;
  onReady?(element: HTMLVideoElement | null): void;
}

export function VideoPlayer({
  videoId,
  available,
  title,
  onTimeChange,
  onReady
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const intentRef = useRef<PlaybackIntent | null>(null);
  const [playback, setPlayback] = useState<PlaybackUrl | null>(null);
  const [loading, setLoading] = useState(available);
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  const rememberIntent = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    intentRef.current = { position: video.currentTime, playing: !video.paused };
  }, []);

  const connectVideo = useCallback((element: HTMLVideoElement | null) => {
    videoRef.current = element;
    onReady?.(element);
  }, [onReady]);

  useEffect(() => {
    if (!available) {
      setPlayback(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    intentRef.current = null;
    setPlayback(null);

    async function refresh(isInitial: boolean) {
      try {
        const next = await getPlaybackUrl(videoId, controller.signal);
        if (controller.signal.aborted) return;
        if (!isInitial) rememberIntent();
        setPlayback(next);
        setError(null);
        setLoading(false);
        refreshTimer = setTimeout(() => void refresh(false), playbackRefreshDelay(next));
      } catch (caught) {
        if (!controller.signal.aborted) {
          const reason = featureFailureMessage(caught, "The video file is unavailable right now.");
          setError(`${reason} Only the video file is unavailable; transcript, outline, insights, conversations, and pins remain usable.`);
          setLoading(false);
        }
      }
    }

    setLoading(true);
    setError(null);
    void refresh(true);
    return () => {
      controller.abort();
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [available, reloadVersion, rememberIntent, videoId]);

  function restoreIntent() {
    const video = videoRef.current;
    const intent = intentRef.current;
    if (!video || !intent) return;
    video.currentTime = Math.min(intent.position, Number.isFinite(video.duration) ? video.duration : intent.position);
    if (intent.playing) void video.play().catch(() => undefined);
    intentRef.current = null;
  }

  if (!available) {
    return (
      <Panel className="video-player video-player--unavailable">
        <p>The video file will be available when transcription is far enough along.</p>
      </Panel>
    );
  }

  if (loading && !playback) return <LoadingState label="Preparing secure video playback…" />;

  if (error && !playback) {
    return (
      <Panel className="video-player video-player--unavailable">
        <h2>Video file unavailable</h2>
        <p>{error}</p>
        <Button onClick={() => setReloadVersion((current) => current + 1)}>Try video again</Button>
      </Panel>
    );
  }

  return (
    <div className="video-player">
      <video
        ref={connectVideo}
        key={playback?.url}
        src={playback?.url}
        controls
        preload="metadata"
        aria-label={title}
        onLoadedMetadata={restoreIntent}
        onTimeUpdate={(event) => onTimeChange(event.currentTarget.currentTime)}
      />
      {error ? <p className="video-player__notice" role="status">Playback refresh failed. The current link may continue working.</p> : null}
    </div>
  );
}
