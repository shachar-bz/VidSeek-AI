import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { allowsBrowsing, type VideoDetail, type VideoOutlineResponse, type VideoTranscript } from "../../api/types";
import { getVideo, getVideoOutline, getVideoTranscript } from "../../api/video";
import { ErrorState, LoadingState, StatusBadge, type StatusTone } from "../../components/ui";
import { ROUTES } from "../../routes";
import { featureFailureMessage } from "../shared";
import { ConversationWorkspace } from "./ConversationWorkspace";
import { VideoDetailsTabs } from "./OutlineInsights";
import { VideoPlayer } from "./VideoPlayer";
import { activeTranscriptIndex } from "./format";

function stageLabel(stage: VideoDetail["stage"]): string {
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

function stageTone(stage: VideoDetail["stage"]): StatusTone {
  if (stage === "ready") return "positive";
  if (stage === "partial") return "caution";
  if (stage === "failed") return "critical";
  return "active";
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
  const playerRef = useRef<HTMLVideoElement | null>(null);
  const rememberPlayer = useCallback((player: HTMLVideoElement | null) => { playerRef.current = player; }, []);

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

  function updateActiveLine(seconds: number) {
    const next = activeTranscriptIndex(transcript?.lines ?? [], seconds);
    if (next === activeLineIndexRef.current) return;
    activeLineIndexRef.current = next;
    setActiveLineIndex(next);
  }

  if (loading && !video) return <LoadingState label="Loading video…" />;
  if (error || !video) return <ErrorState title="Unable to load video" message={error ?? "This video is unavailable."} actionLabel="Try again" onAction={() => setReloadVersion((current) => current + 1)} />;

  const browsing = allowsBrowsing(video.stage);
  const approximate = video.stage === "partial";
  return (
    <div className="feature-page video-page">
      <header className="feature-page__heading video-page__heading">
        <div>
          <p className="eyebrow"><Link to={ROUTES.library}>Library</Link> / {video.source_site}</p>
          <h1>{video.title}</h1>
          <div className="video-page__metadata"><StatusBadge tone={stageTone(video.stage)}>{stageLabel(video.stage)}</StatusBadge>{video.duration_seconds !== null ? <span>{Math.round(video.duration_seconds / 60)} min</span> : null}{video.transcript_language ? <span>{video.transcript_language}</span> : null}</div>
        </div>
      </header>
      {approximate ? <div className="inline-notice" role="status"><strong>Partial transcript:</strong> timestamps, seeking, and timestamp-like references in answers may be unreliable. All video features remain available.</div> : null}
      {video.stage === "failed" ? <div className="inline-notice" role="alert">Processing failed. Chat is unavailable, and video artifacts may be incomplete.</div> : null}
      {artifactError ? <div className="inline-notice" role="status">{artifactError}</div> : null}
      <div className="video-workspace-grid">
        <div className="video-viewer-column">
          <VideoPlayer videoId={videoId} available={browsing} title={video.title} captionLines={transcript?.lines} captionLanguage={video.transcript_language} onTimeChange={updateActiveLine} onReady={rememberPlayer} />
          <VideoDetailsTabs video={video} transcript={transcript} outline={outline} activeLineIndex={activeLineIndex} approximate={approximate} onSeek={seek} />
        </div>
        <ConversationWorkspace video={video} approximate={approximate} onSeek={seek} />
      </div>
    </div>
  );
}
