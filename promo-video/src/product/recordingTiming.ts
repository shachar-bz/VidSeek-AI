import { Easing, interpolate } from "remotion";

// One piece of a source recording: play [start, end] source seconds at `speed`,
// or hold the frame at `start` for `holdSeconds`.
export type ClipSegment =
  | { start: number; end: number; speed: number }
  | { start: number; holdSeconds: number };

export const segmentOutputSeconds = (segment: ClipSegment) =>
  "holdSeconds" in segment ? segment.holdSeconds : (segment.end - segment.start) / segment.speed;

// Maps a moment in the source recording to the output second where it appears,
// so overlays (clicks, lifted chips) can be pinned to real events.
export const outputSecondsAtSourceTime = (segments: ClipSegment[], sourceSeconds: number): number => {
  let elapsed = 0;
  for (const segment of segments) {
    if ("holdSeconds" in segment) {
      if (Math.abs(segment.start - sourceSeconds) < 1e-3) return elapsed;
    } else if (sourceSeconds >= segment.start && sourceSeconds <= segment.end) {
      return elapsed + (sourceSeconds - segment.start) / segment.speed;
    }
    elapsed += segmentOutputSeconds(segment);
  }
  return elapsed;
};

// A camera framing inside the source: center point and visible width in source pixels.
export type CameraFraming = { centerX: number; centerY: number; width: number };
export type CameraKeyframe = CameraFraming & { at: number };

// Slow ease-in-out between keyframes; holds the first/last framing outside them.
export const interpolateCamera = (keyframes: CameraKeyframe[], seconds: number): CameraFraming => {
  if (keyframes.length === 1 || seconds <= keyframes[0].at) return keyframes[0];
  for (let index = 1; index < keyframes.length; index++) {
    const previous = keyframes[index - 1];
    const next = keyframes[index];
    if (seconds <= next.at) {
      const progress = interpolate(seconds, [previous.at, next.at], [0, 1], {
        easing: Easing.bezier(0.65, 0, 0.35, 1),
      });
      return {
        centerX: previous.centerX + (next.centerX - previous.centerX) * progress,
        centerY: previous.centerY + (next.centerY - previous.centerY) * progress,
        width: previous.width + (next.width - previous.width) * progress,
      };
    }
  }
  return keyframes[keyframes.length - 1];
};
