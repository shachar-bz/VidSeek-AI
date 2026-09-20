import type { VideoDetail, VideoOutlineResponse } from "../../api/types";
import { Button, EmptyState, Panel } from "../../components/ui";
import { formatTimestamp } from "./format";

export function OutlinePanel({
  outline,
  stageLabel,
  approximate,
  onSeek
}: {
  outline: VideoOutlineResponse | null;
  stageLabel: string;
  approximate: boolean;
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
                title={approximate ? "Seek using this approximate chapter time" : "Seek to this chapter"}
                onClick={() => onSeek(chapter.start_seconds)}
              >
                {approximate ? "≈" : ""}{formatTimestamp(chapter.start_seconds)}–{formatTimestamp(chapter.end_seconds)}
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
