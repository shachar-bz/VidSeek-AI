// Splits an answer into plain text and the timestamps it cites, so each timestamp can seek.

export type AnswerSegment =
  | { kind: "text"; text: string }
  | { kind: "citation"; text: string; seconds: number };

// Mirrors the citation grammar the backend checks answers against, in
// backend/video_agent/citations.py, the same way frontend/src/pages/video/format.ts does.
const TIME = String.raw`(?:\d{1,2}:)?\d{1,2}:[0-5]\d`;
const CITATION = new RegExp(
  `\\[\\s*(${TIME})\\s*(?:[-–—]\\s*${TIME}\\s*)?\\]`,
  "g",
);

export function timestampSeconds(timestamp: string): number {
  return timestamp
    .split(":")
    .reduce((total, part) => total * 60 + Number(part), 0);
}

export function splitAnswerCitations(content: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let cursor = 0;
  for (const match of content.matchAll(CITATION)) {
    const start = match.index ?? 0;
    if (start > cursor)
      segments.push({ kind: "text", text: content.slice(cursor, start) });
    segments.push({
      kind: "citation",
      text: match[0],
      seconds: timestampSeconds(match[1] ?? "0:00"),
    });
    cursor = start + match[0].length;
  }
  if (cursor < content.length)
    segments.push({ kind: "text", text: content.slice(cursor) });
  return segments;
}

export function formatTimestamp(seconds: number): string {
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = String(rounded % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}`
    : `${minutes}:${remainder}`;
}
