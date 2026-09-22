import type { TranscriptLine } from "../../api/types";

/**
 * The transcript, rebuilt as the WebVTT the player hands to the browser's own caption
 * track. Using a real text track is what keeps the subtitles synchronized, positioned
 * inside the video frame, and toggleable from the player controls in fullscreen too.
 */

const MINIMUM_CUE_SECONDS = 0.4;

function cueTime(seconds: number): string {
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const remainder = safe % 60;
  const wholeSeconds = Math.floor(remainder);
  const milliseconds = Math.round((remainder - wholeSeconds) * 1000);
  return [
    String(hours).padStart(2, "0"),
    String(minutes).padStart(2, "0"),
    `${String(wholeSeconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`
  ].join(":");
}

/** WebVTT reads `-->` as a timing line and `<` as markup, so neither may reach cue text. */
function cueText(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function buildCaptionsVtt(lines: TranscriptLine[]): string {
  const cues: string[] = [];

  lines.forEach((line, index) => {
    const text = cueText(line.text);
    if (!text) return;
    const start = Math.max(0, line.start_seconds);
    const nextStart = lines[index + 1]?.start_seconds ?? Number.POSITIVE_INFINITY;
    const ceiling = Math.max(start, Math.min(line.end_seconds, nextStart));
    const end = ceiling > start ? ceiling : start + MINIMUM_CUE_SECONDS;
    cues.push(`${cueTime(start)} --> ${cueTime(end)}\n${text}`);
  });

  return `WEBVTT\n\n${cues.join("\n\n")}\n`;
}
