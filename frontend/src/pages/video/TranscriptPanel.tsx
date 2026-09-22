import { useEffect, useRef, useState } from "react";

import type { VideoTranscript } from "../../api/types";
import { Button, EmptyState, Panel } from "../../components/ui";
import { formatTimestamp } from "./format";

/** Keeps the spoken line in view without scrolling the page around the transcript. */
function scrollLineIntoView(list: HTMLOListElement, line: HTMLLIElement) {
  const target = line.offsetTop - (list.clientHeight - line.clientHeight) / 2;
  const top = Math.max(0, Math.min(target, list.scrollHeight - list.clientHeight));
  if (typeof list.scrollTo === "function") list.scrollTo({ top, behavior: "smooth" });
  else list.scrollTop = top;
}

export interface TranscriptPanelProps {
  transcript: VideoTranscript | null;
  activeIndex: number;
  approximate: boolean;
  embedded?: boolean;
  onSeek(seconds: number): void;
}

export function TranscriptPanel({
  transcript,
  activeIndex,
  approximate,
  embedded = false,
  onSeek
}: TranscriptPanelProps) {
  const lines = transcript?.lines ?? [];
  const [following, setFollowing] = useState(true);
  const listRef = useRef<HTMLOListElement | null>(null);
  const lineRefs = useRef(new Map<number, HTMLLIElement>());

  useEffect(() => {
    if (!following || activeIndex < 0) return;
    const list = listRef.current;
    const line = lineRefs.current.get(activeIndex);
    if (list && line) scrollLineIntoView(list, line);
  }, [activeIndex, following]);

  useEffect(() => {
    setFollowing(true);
  }, [transcript?.video_id]);

  function seekToLine(seconds: number) {
    setFollowing(true);
    onSeek(seconds);
  }

  if (lines.length === 0) {
    const emptyContent = (
      <>
        <div className="video-section__heading"><h2>Transcript</h2></div>
        <EmptyState title="Transcript not available yet" description="The complete transcript will appear here as processing progresses." />
      </>
    );
    return embedded
      ? <section className="video-section transcript-panel transcript-panel--embedded">{emptyContent}</section>
      : <Panel className="video-section transcript-panel">{emptyContent}</Panel>;
  }

  const content = (
    <>
      <div className="video-section__heading video-section__heading--split">
        <div>
          <h2>Transcript</h2>
          <p>{lines.length.toLocaleString()} lines · {transcript?.timing_fidelity ?? "unknown"} timing</p>
        </div>
        {!following ? (
          <div className="transcript-actions">
            <Button variant="ghost" onClick={() => setFollowing(true)}>Follow playback</Button>
          </div>
        ) : null}
      </div>
      {approximate ? <p className="inline-notice">Timestamps are approximate for this partial result. Seeking may be inaccurate.</p> : null}
      <ol
        className="transcript-lines"
        ref={listRef}
        onWheel={() => setFollowing(false)}
        onTouchMove={() => setFollowing(false)}
      >
        {lines.map((line, index) => {
          const active = index === activeIndex;
          return (
            <li
              key={`${line.index}-${line.start_seconds}`}
              ref={(element) => {
                if (element) lineRefs.current.set(index, element);
                else lineRefs.current.delete(index);
              }}
              className={active ? "transcript-line transcript-line--active" : "transcript-line"}
              aria-current={active ? "true" : undefined}
            >
              <button
                className="transcript-line__body"
                type="button"
                title={approximate ? "Seek using this approximate timestamp" : "Seek to this timestamp"}
                onClick={() => seekToLine(line.start_seconds)}
              >
                <span className="transcript-line__time">{approximate ? "≈" : ""}{formatTimestamp(line.start_seconds)}</span>
                <span className="transcript-line__text">{line.text}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </>
  );

  return embedded
    ? <section className="video-section transcript-panel transcript-panel--embedded">{content}</section>
    : <Panel className="video-section transcript-panel">{content}</Panel>;
}
