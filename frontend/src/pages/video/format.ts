import type { TranscriptLine } from "../../api/types";

export function formatTimestamp(seconds: number): string {
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function activeTranscriptIndex(lines: TranscriptLine[], seconds: number): number {
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

  if (candidate === -1) return -1;
  const line = lines[candidate];
  return line && seconds <= line.end_seconds ? candidate : -1;
}

export function transcriptLineText(line: TranscriptLine, approximate = false): string {
  return `[${approximate ? "≈" : ""}${formatTimestamp(line.start_seconds)}] ${line.text}`;
}
