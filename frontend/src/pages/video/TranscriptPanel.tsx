import { useEffect, useRef, useState, type ChangeEvent } from "react";

import type { TranscriptLine, VideoTranscript } from "../../api/types";
import { Button, EmptyState, Panel } from "../../components/ui";
import { formatTimestamp, transcriptLineText } from "./format";

async function copyText(value: string): Promise<void> {
  await navigator.clipboard.writeText(value);
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
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [selectionAnchor, setSelectionAnchor] = useState<number | null>(null);
  const [following, setFollowing] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const lineRefs = useRef(new Map<number, HTMLLIElement>());

  useEffect(() => {
    if (!following || activeIndex < 0) return;
    lineRefs.current.get(activeIndex)?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, following]);

  useEffect(() => {
    setSelected(new Set());
    setSelectionAnchor(null);
  }, [transcript?.video_id]);

  function updateSelection(index: number, checked: boolean, shiftKey: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (shiftKey && selectionAnchor !== null) {
        const start = Math.min(selectionAnchor, index);
        const end = Math.max(selectionAnchor, index);
        for (let cursor = start; cursor <= end; cursor += 1) {
          if (checked) next.add(cursor);
          else next.delete(cursor);
        }
      } else if (checked) next.add(index);
      else next.delete(index);
      return next;
    });
    setSelectionAnchor(index);
  }

  async function copyLines(linesToCopy: TranscriptLine[]) {
    try {
      await copyText(linesToCopy.map((line) => transcriptLineText(line, approximate)).join("\n"));
      setCopyStatus(linesToCopy.length === 1 ? "Line copied" : `${linesToCopy.length} lines copied`);
    } catch {
      setCopyStatus("Copy failed. Select the transcript text and copy it manually.");
    }
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
        <div className="transcript-actions">
          {!following ? <Button variant="ghost" onClick={() => setFollowing(true)}>Follow playback</Button> : null}
          <Button
            variant="ghost"
            disabled={selected.size === 0}
            onClick={() => void copyLines(lines.filter((_, index) => selected.has(index)))}
          >
            Copy selected ({selected.size})
          </Button>
        </div>
      </div>
      {approximate ? <p className="inline-notice">Timestamps are approximate for this partial result. Seeking and copied timestamp references may be inaccurate.</p> : null}
      <p className="visually-hidden" aria-live="polite">{copyStatus}</p>
      <ol
        className="transcript-lines"
        onWheel={() => setFollowing(false)}
        onPointerDown={() => setFollowing(false)}
      >
        {lines.map((line, index) => {
          const active = index === activeIndex;
          const selectedLine = selected.has(index);
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
              <input
                type="checkbox"
                aria-label={`Select transcript line ${index + 1}`}
                checked={selectedLine}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  updateSelection(
                    index,
                    event.target.checked,
                    Boolean((event.nativeEvent as unknown as { shiftKey?: boolean }).shiftKey)
                  )
                }
              />
              <button
                className="transcript-line__time"
                type="button"
                title={approximate ? "Seek using this approximate timestamp" : "Seek to this timestamp"}
                onClick={() => onSeek(line.start_seconds)}
              >
                {approximate ? "≈" : ""}{formatTimestamp(line.start_seconds)}
              </button>
              <span>{line.text}</span>
              <button
                className="transcript-line__copy"
                type="button"
                aria-label={`Copy transcript line ${index + 1}`}
                onClick={() => void copyLines([line])}
              >
                Copy
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
