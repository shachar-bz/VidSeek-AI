import { useState } from "react";

import type { VideoDetail, VideoOutlineResponse, VideoTranscript } from "../../api/types";
import { Button, EmptyState, Panel } from "../../components/ui";
import { formatTimestamp } from "./format";
import { TranscriptPanel } from "./TranscriptPanel";

export function OutlinePanel({
  outline,
  stageLabel,
  onSeek
}: {
  outline: VideoOutlineResponse | null;
  stageLabel: string;
  onSeek(seconds: number): void;
}) {
  const chapters = outline?.chapters ?? [];
  return (
    <Panel className="video-section outline-panel">
      <div className="video-section__heading"><h2>Outline</h2></div>
      {chapters.length === 0 ? (
        <EmptyState title={`Video is ${stageLabel.toLowerCase()}`} description="Chapters will appear here when the video has been understood." />
      ) : (
        <ol className="chapter-list">
          {chapters.map((chapter) => (
            <li key={chapter.chapter_id}>
              <button
                className="chapter-list__time"
                type="button"
                title="Seek to this chapter"
                onClick={() => onSeek(chapter.start_seconds)}
              >
                {formatTimestamp(chapter.start_seconds)}–{formatTimestamp(chapter.end_seconds)}
              </button>
              <div><h3>{chapter.title}</h3><p>{chapter.summary}</p></div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

export function InsightsPanel({
  video,
  onSuggestedQuestion
}: {
  video: VideoDetail;
  onSuggestedQuestion(question: string): void;
}) {
  const insights = video.insights;
  return (
    <Panel className="video-section insights-panel">
      <div className="video-section__heading"><h2>Generated insights</h2></div>
      {!insights ? (
        <EmptyState title="Insights are still processing" description="The stored summary, takeaways, and questions will appear when they are ready." />
      ) : (
        <div className="insights-content">
          <section><h3>Summary</h3><p>{insights.summary}</p></section>
          <section><h3>Key takeaways</h3><ul>{insights.takeaways.map((takeaway, index) => <li key={index}>{takeaway}</li>)}</ul></section>
          <section className="suggested-questions"><h3>Suggested questions</h3><div>{insights.suggested_questions.map((question, index) => <Button variant="ghost" key={index} onClick={() => onSuggestedQuestion(question)}>{question}</Button>)}</div></section>
        </div>
      )}
    </Panel>
  );
}

export function VideoDetailsTabs({
  video,
  transcript,
  outline,
  activeLineIndex,
  syncTarget,
  onSeek
}: {
  video: VideoDetail;
  transcript: VideoTranscript | null;
  outline: VideoOutlineResponse | null;
  activeLineIndex: number;
  syncTarget?: { index: number } | null;
  onSeek(seconds: number): void;
}) {
  const [activeTab, setActiveTab] = useState<"transcript" | "summary">("transcript");
  const insights = video.insights;
  const chapters = outline?.chapters ?? [];

  return (
    <Panel className="video-details-tabs">
      <div className="video-details-tabs__list" role="tablist" aria-label="Video details">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "transcript"}
          aria-controls="video-transcript-panel"
          id="video-transcript-tab"
          onClick={() => setActiveTab("transcript")}
        >
          Transcript
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "summary"}
          aria-controls="video-summary-panel"
          id="video-summary-tab"
          onClick={() => setActiveTab("summary")}
        >
          Summary
        </button>
      </div>

      <div
        id="video-transcript-panel"
        role="tabpanel"
        aria-labelledby="video-transcript-tab"
        hidden={activeTab !== "transcript"}
      >
        {/* Mounted only while visible, so coming back to the tab scrolls to the spoken line. */}
        {activeTab === "transcript" ? (
          <TranscriptPanel
            transcript={transcript}
            activeIndex={activeLineIndex}
            syncTarget={syncTarget}
            embedded
            onSeek={onSeek}
          />
        ) : null}
      </div>

      <div
        className="video-summary-panel"
        id="video-summary-panel"
        role="tabpanel"
        aria-labelledby="video-summary-tab"
        hidden={activeTab !== "summary"}
      >
        {!insights ? (
          <EmptyState title="Summary is still processing" description="The summary and key points will appear here when they are ready." />
        ) : (
          <div className="video-summary-panel__content">
            <section>
              <h2>Summary</h2>
              <p>{insights.summary}</p>
            </section>
            <section>
              <h2>{insights.takeaways.length === 5 ? "5 key points" : "Key points"}</h2>
              <ol className="key-points-list">
                {insights.takeaways.map((takeaway, index) => <li key={index}>{takeaway}</li>)}
              </ol>
            </section>
            {chapters.length > 0 ? (
              <section>
                <h2>Chapters</h2>
                <ol className="summary-chapter-list">
                  {chapters.map((chapter) => (
                    <li key={chapter.chapter_id}>
                      <button type="button" onClick={() => onSeek(chapter.start_seconds)}>
                        {formatTimestamp(chapter.start_seconds)}
                      </button>
                      <div><h3>{chapter.title}</h3><p>{chapter.summary}</p></div>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </div>
        )}
      </div>
    </Panel>
  );
}
