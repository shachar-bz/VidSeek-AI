import type { TranscriptLine } from "../../api/types";

export type MessageSegment =
  | { kind: "text"; text: string }
  | { kind: "citation"; text: string; seconds: number };

// Mirrors the citation grammar the backend checks answers against, in
// backend/video_agent/citations.py. A citation the agent wrote has already been verified
// against what its tools returned; one written before that check existed has not, which is
// why this only decides what is seekable and never what is true.
const TIME = String.raw`(?:\d{1,2}:)?\d{1,2}:[0-5]\d`;
const CITATION = new RegExp(`\\[\\s*(${TIME})\\s*(?:[-–—]\\s*${TIME}\\s*)?\\]`, "g");

export function timestampSeconds(timestamp: string): number {
  return timestamp.split(":").reduce((total, part) => total * 60 + Number(part), 0);
}

export function splitMessageCitations(content: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  let cursor = 0;

  for (const match of content.matchAll(CITATION)) {
    const start = match.index ?? 0;
    if (start > cursor) segments.push({ kind: "text", text: content.slice(cursor, start) });
    segments.push({ kind: "citation", text: match[0], seconds: timestampSeconds(match[1] ?? "0:00") });
    cursor = start + match[0].length;
  }

  if (cursor < content.length) segments.push({ kind: "text", text: content.slice(cursor) });
  return segments;
}

export function formatTimestamp(seconds: number): string {
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

/** The last line that has begun by `seconds`, even if it already ended (a gap before the next). */
export function startedLineIndex(lines: TranscriptLine[], seconds: number): number {
  let low = 0;
  let high = lines.length - 1;
  let candidate = -1;

  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const line = lines[middle];
    if (!line) break;
    if (line.start_seconds <= seconds) {
      candidate = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }

  return candidate;
}

export function activeTranscriptIndex(lines: TranscriptLine[], seconds: number): number {
  const candidate = startedLineIndex(lines, seconds);
  const line = lines[candidate];
  return line && seconds <= line.end_seconds ? candidate : -1;
}
