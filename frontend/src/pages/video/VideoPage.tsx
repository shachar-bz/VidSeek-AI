import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { allowsBrowsing, type VideoDetail, type VideoOutlineResponse, type VideoTranscript } from "../../api/types";
import { getVideo, getVideoOutline, getVideoTranscript } from "../../api/video";
import { ErrorState, LoadingState, StatusBadge, type StatusTone } from "../../components/ui";
import { featureFailureMessage, sourceLabel } from "../shared";
import { ConversationWorkspace, type PlayerPosition } from "./ConversationWorkspace";
import { VideoDetailsTabs } from "./OutlineInsights";
import { VideoPlayer } from "./VideoPlayer";
import { activeTranscriptIndex, startedLineIndex } from "./format";

function stageLabel(stage: VideoDetail["stage"]): string {
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

function stageTone(stage: VideoDetail["stage"]): StatusTone {
  if (stage === "ready") return "positive";
  if (stage === "failed") return "critical";
  return "active";
}

/** `en` reads as "English"; a code the browser cannot name is shown as it is. */
export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function VideoPage() {
  const { videoId = "" } = useParams();
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [transcript, setTranscript] = useState<VideoTranscript | null>(null);
  const [outline, setOutline] = useState<VideoOutlineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [activeLineIndex, setActiveLineIndex] = useState(-1);
  const activeLineIndexRef = useRef(-1);
  // A new object per jump, so the transcript re-syncs even when the line did not change.
  const [syncTarget, setSyncTarget] = useState<{ index: number } | null>(null);
  const playerRef = useRef<HTMLVideoElement | null>(null);
  const rememberPlayer = useCallback((player: HTMLVideoElement | null) => { playerRef.current = player; }, []);
  const readPlayerPosition = useCallback((): PlayerPosition | null => {
    const player = playerRef.current;
    return player ? { seconds: player.currentTime, paused: player.paused } : null;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setVideo(null);
    setError(null);
    setArtifactError(null);
    setTranscript(null);
    setOutline(null);
    activeLineIndexRef.current = -1;
    setActiveLineIndex(-1);
    setSyncTarget(null);

    void (async () => {
      try {
        const detail = await getVideo(videoId, controller.signal);
        if (controller.signal.aborted) return;
        setVideo(detail);
        if (allowsBrowsing(detail.stage)) {
          const [transcriptResult, outlineResult] = await Promise.allSettled([
            getVideoTranscript(videoId, controller.signal),
            getVideoOutline(videoId, controller.signal)
          ]);
          if (controller.signal.aborted) return;
          if (transcriptResult.status === "fulfilled") setTranscript(transcriptResult.value);
          if (outlineResult.status === "fulfilled") setOutline(outlineResult.value);
          const rejected = [transcriptResult, outlineResult].find((result) => result.status === "rejected");
          if (rejected?.status === "rejected") {
            setArtifactError(featureFailureMessage(rejected.reason, "Some video content could not be loaded."));
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) setError(featureFailureMessage(caught, "We couldn’t load this video."));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [reloadVersion, videoId]);

  function seek(seconds: number) {
    const player = playerRef.current;
    if (!player) return;
    player.currentTime = seconds;
    updateActiveLine(seconds);
  }

  // Every jump (citation, chapter, transcript line, or the native scrubber) ends in `seeked`.
  function syncTranscriptToPlayer(seconds: number) {
    updateActiveLine(seconds);
    setSyncTarget({ index: startedLineIndex(transcript?.lines ?? [], seconds) });
  }

  function updateActiveLine(seconds: number) {
    const next = activeTranscriptIndex(transcript?.lines ?? [], seconds);
    if (next === activeLineIndexRef.current) return;
    activeLineIndexRef.current = next;
    setActiveLineIndex(next);
  }

  if (loading && !video) return <LoadingState label="Loading video…" />;
  if (error || !video) return <ErrorState title="Unable to load video" message={error ?? "This video is unavailable."} actionLabel="Try again" onAction={() => setReloadVersion((current) => current + 1)} />;

  const browsing = allowsBrowsing(video.stage);
  return (
    <div className="feature-page video-page">
      <header className="feature-page__heading video-page__heading">
        <div>
          <h1>{video.title}</h1>
          <div className="video-page__metadata">{video.stage !== "ready" ? <StatusBadge tone={stageTone(video.stage)}>{stageLabel(video.stage)}</StatusBadge> : null}<span>{sourceLabel(video)}</span>{video.duration_seconds !== null ? <span>{Math.round(video.duration_seconds / 60)} min</span> : null}{video.transcript_language ? <span>{languageName(video.transcript_language)}</span> : null}</div>
        </div>
      </header>
      {video.stage === "failed" ? <div className="inline-notice" role="alert">Processing failed. Chat is unavailable, and video artifacts may be incomplete.</div> : null}
      {artifactError ? <div className="inline-notice" role="status">{artifactError}</div> : null}
      <div className="video-workspace-grid">
        <div className="video-viewer-column">
          <VideoPlayer videoId={videoId} available={browsing} title={video.title} captionLines={transcript?.lines} captionLanguage={video.transcript_language} onTimeChange={updateActiveLine} onSeeked={syncTranscriptToPlayer} onReady={rememberPlayer} />
          <VideoDetailsTabs video={video} transcript={transcript} outline={outline} activeLineIndex={activeLineIndex} syncTarget={syncTarget} onSeek={seek} />
        </div>
        <ConversationWorkspace video={video} onSeek={seek} playerPosition={readPlayerPosition} />
      </div>
    </div>
  );
}
