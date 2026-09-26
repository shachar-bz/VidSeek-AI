import React from "react";
import { Easing, Freeze, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import { FPS } from "../timeline";
import { shadows } from "../theme";

// One piece of a source recording: play [start, end] seconds at `speed`,
// or hold the frame at `start` for `holdSeconds`.
export type ClipSegment =
  | { start: number; end: number; speed: number }
  | { start: number; holdSeconds: number };

export const segmentOutputSeconds = (segment: ClipSegment) =>
  "holdSeconds" in segment ? segment.holdSeconds : (segment.end - segment.start) / segment.speed;

export const totalOutputSeconds = (segments: ClipSegment[]) =>
  segments.reduce((sum, segment) => sum + segmentOutputSeconds(segment), 0);

// Maps a moment in the source recording to the output second where it appears,
// so overlays (clicks, answer cards) can be pinned to real events.
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

const SegmentedVideo: React.FC<{ src: string; segments: ClipSegment[] }> = ({ src, segments }) => {
  let fromFrame = 0;
  return (
    <>
      {segments.map((segment, index) => {
        const durationInFrames = Math.max(1, Math.round(segmentOutputSeconds(segment) * FPS));
        const sequenceStart = fromFrame;
        fromFrame += durationInFrames;
        const video =
          "holdSeconds" in segment ? (
            <Freeze frame={0}>
              <OffthreadVideo src={staticFile(src)} trimBefore={Math.round(segment.start * FPS)} muted />
            </Freeze>
          ) : (
            <OffthreadVideo
              src={staticFile(src)}
              trimBefore={Math.round(segment.start * FPS)}
              playbackRate={segment.speed}
              muted
            />
          );
        return (
          <Sequence key={index} from={sequenceStart} durationInFrames={durationInFrames} layout="none">
            {video}
          </Sequence>
        );
      })}
    </>
  );
};

// A floating, rounded "screen" that shows a region of some source content through a moving camera.
export const CameraFrame: React.FC<{
  sourceWidth: number;
  sourceHeight: number;
  camera: CameraKeyframe[];
  boxWidth: number;
  boxHeight: number;
  content: React.ReactNode; // rendered at source size
  style?: React.CSSProperties;
  borderRadius?: number;
  children?: React.ReactNode; // overlays positioned in box coordinates
}> = ({ sourceWidth, sourceHeight, camera, boxWidth, boxHeight, content, style, borderRadius = 22, children }) => {
  const frame = useCurrentFrame();
  const framing = interpolateCamera(camera, frame / FPS);
  const scale = boxWidth / framing.width;
  const visibleHeight = boxHeight / scale;
  const left = -(framing.centerX - framing.width / 2) * scale;
  const top = -(framing.centerY - visibleHeight / 2) * scale;
  return (
    <div
      style={{
        position: "absolute",
        width: boxWidth,
        height: boxHeight,
        borderRadius,
        overflow: "hidden",
        background: "#fff",
        boxShadow: shadows.floatingScreen,
        ...style,
      }}
    >
      <div
        style={{
          position: "absolute",
          left,
          top,
          width: sourceWidth,
          height: sourceHeight,
          transform: `scale(${scale})`,
          transformOrigin: "0 0",
        }}
      >
        {content}
      </div>
      {children}
    </div>
  );
};

// A real screen recording, trimmed into segments, inside a CameraFrame.
export const ScreenRecording: React.FC<
  Omit<React.ComponentProps<typeof CameraFrame>, "content"> & { src: string; segments: ClipSegment[] }
> = ({ src, segments, ...frameProps }) => (
  <CameraFrame {...frameProps} content={<SegmentedVideo src={src} segments={segments} />} />
);

// Converts a point in source pixels to box pixels for the camera at `seconds`.
export const sourcePointToBox = (
  camera: CameraKeyframe[],
  seconds: number,
  boxWidth: number,
  boxHeight: number,
  sourceX: number,
  sourceY: number,
) => {
  const framing = interpolateCamera(camera, seconds);
  const scale = boxWidth / framing.width;
  const visibleHeight = boxHeight / scale;
  return {
    x: (sourceX - (framing.centerX - framing.width / 2)) * scale,
    y: (sourceY - (framing.centerY - visibleHeight / 2)) * scale,
    scale,
  };
};
