import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { getPlaybackUrl } from "../../api/video";
import {
  PLAYBACK_URL_REFRESH_MARGIN_SECONDS,
  type PlaybackUrl,
  type TranscriptLine
} from "../../api/types";
import { Button, LoadingState, Panel } from "../../components/ui";
import { featureFailureMessage } from "../shared";
import { buildCaptionsVtt } from "./captions";

const MINIMUM_REFRESH_DELAY_MS = 1_000;
const NO_CAPTIONS: TranscriptLine[] = [];
// Chrome hides its control bar this long after the last pointer activity while playing.
const CONTROLS_IDLE_MS = 3_000;

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

function captionTrack(video: HTMLVideoElement): TextTrack | null {
  return video.textTracks?.[0] ?? null;
}

export interface VideoPlayerProps {
  videoId: string;
  available: boolean;
  title: string;
  captionLines?: TranscriptLine[];
  captionLanguage?: string | null;
  onTimeChange(seconds: number): void;
  onSeeked?(seconds: number): void;
  onReady?(element: HTMLVideoElement | null): void;
}

export function VideoPlayer({
  videoId,
  available,
  title,
  captionLines = NO_CAPTIONS,
  captionLanguage,
  onTimeChange,
  onSeeked,
  onReady
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const intentRef = useRef<PlaybackIntent | null>(null);
  const captionsOnRef = useRef(false);
  const [captionsOn, setCaptionsOn] = useState(false);
  // Mirrors the native control bar: shown while paused, or while the pointer was recently active.
  const [paused, setPaused] = useState(true);
  const [pointerActive, setPointerActive] = useState(false);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const [playback, setPlayback] = useState<PlaybackUrl | null>(null);
  const [loading, setLoading] = useState(available);
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  // The browser's own caption track: it keeps the cues in sync, draws them inside the
  // video frame in fullscreen as well, and puts the CC toggle in the player controls.
  const captionsUrl = useMemo(() => {
    if (captionLines.length === 0) return null;
    if (typeof URL.createObjectURL !== "function") return null;
    return URL.createObjectURL(new Blob([buildCaptionsVtt(captionLines)], { type: "text/vtt" }));
  }, [captionLines]);

  useEffect(() => () => { if (captionsUrl) URL.revokeObjectURL(captionsUrl); }, [captionsUrl]);

  useEffect(() => () => clearTimeout(idleTimerRef.current), []);

  function showControls() {
    setPointerActive(true);
    clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => setPointerActive(false), CONTROLS_IDLE_MS);
  }

  function hideControls() {
    clearTimeout(idleTimerRef.current);
    setPointerActive(false);
  }

  // The video element is never the fullscreen element: the frame around it is, so the CC
  // control stays on screen there. Chrome only offers its own captions entry through an
  // overflow menu, which is why the player carries a button of its own. The frame has to
  // be requested from the click itself: a request made after the video went fullscreen no
  // longer has the user activation the browser requires, and is refused.
  function toggleFullscreen() {
    const frame = frameRef.current;
    if (!frame) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
    } else {
      void frame.requestFullscreen().catch(() => undefined);
    }
  }

  function onVideoDoubleClick(event: MouseEvent<HTMLVideoElement>) {
    // Chrome's double-click default makes the video element fullscreen; take the frame instead.
    event.preventDefault();
    toggleFullscreen();
  }

  function applyCaptionMode() {
    const track = videoRef.current ? captionTrack(videoRef.current) : null;
    if (track) track.mode = captionsOnRef.current ? "showing" : "disabled";
  }

  function toggleCaptions() {
    captionsOnRef.current = !captionsOnRef.current;
    setCaptionsOn(captionsOnRef.current);
    applyCaptionMode();
  }

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
          setError(`${reason} Only the video file is unavailable; transcript, summary, chats, and pins remain usable.`);
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

  function onLoadedMetadata() {
    applyCaptionMode();
    restoreIntent();
  }

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
      <div
        className={captionsUrl ? "video-player__frame video-player__frame--with-captions" : "video-player__frame"}
        ref={frameRef}
        onPointerMove={showControls}
        onPointerDown={showControls}
        onPointerLeave={hideControls}
        onKeyDown={showControls}
      >
        <video
          ref={connectVideo}
          key={playback?.url}
          src={playback?.url}
          controls
          preload="metadata"
          aria-label={title}
          onLoadedMetadata={onLoadedMetadata}
          onPlay={() => setPaused(false)}
          onPause={() => setPaused(true)}
          onEnded={() => setPaused(true)}
          onDoubleClick={onVideoDoubleClick}
          onSeeked={(event) => onSeeked?.(event.currentTarget.currentTime)}
          onTimeUpdate={(event) => onTimeChange(event.currentTarget.currentTime)}
        >
          {captionsUrl ? (
            <track
              kind="captions"
              label="Transcript"
              src={captionsUrl}
              srcLang={captionLanguage ?? "en"}
            />
          ) : null}
        </video>
        <div className={paused || pointerActive ? "video-player__controls video-player__controls--visible" : "video-player__controls"}>
          {captionsUrl ? (
            <button
              className={captionsOn ? "video-player__control video-player__control--on" : "video-player__control"}
              type="button"
              aria-pressed={captionsOn}
              title={captionsOn ? "Turn subtitles off" : "Turn subtitles on"}
              onClick={toggleCaptions}
            >
              <span aria-hidden="true">CC</span>
              <span className="visually-hidden">{captionsOn ? "Turn subtitles off" : "Turn subtitles on"}</span>
            </button>
          ) : null}
        </div>
        {/* Sits over the browser's own fullscreen button, whose icon shows through, so its
            click reaches the frame's fullscreen instead of the video's. */}
        <button
          className="video-player__fullscreen-hitbox"
          type="button"
          title="Full screen"
          aria-label="Full screen"
          onClick={toggleFullscreen}
        />
      </div>
      {error ? <p className="video-player__notice" role="status">Playback refresh failed. The current link may continue working.</p> : null}
    </div>
  );
}
