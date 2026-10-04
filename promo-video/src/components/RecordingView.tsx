import React from "react";
import { Freeze, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import type { RealClick, Recording, RecordingMedia, SourceRect } from "../product/recordings";
import { FPS } from "../timeline";
import { CameraFraming, CameraKeyframe, ClipSegment, interpolateCamera, outputSecondsAtSourceTime, segmentOutputSeconds } from "../product/recordingTiming";

// Keeps a framing inside the page rect, so the box is always filled with page (no bars).
const clampFraming = (framing: CameraFraming, pageRect: SourceRect, aspect: number): CameraFraming => {
  const width = Math.min(framing.width, pageRect.width, pageRect.height * aspect);
  const height = width / aspect;
  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
  return {
    width,
    centerX: clamp(framing.centerX, pageRect.x + width / 2, pageRect.x + pageRect.width - width / 2),
    centerY: clamp(framing.centerY, pageRect.y + height / 2, pageRect.y + pageRect.height - height / 2),
  };
};

// The whole page, cropped to the box's aspect ratio around the page's center.
const wholePageCamera = (pageRect: SourceRect): CameraKeyframe[] => [
  { at: 0, centerX: pageRect.x + pageRect.width / 2, centerY: pageRect.y + pageRect.height / 2, width: pageRect.width },
];

// The camera framing at a scene second, as it will be drawn in a box of the given size.
export const recordingFramingAt = (recording: Recording, seconds: number, boxWidth: number, boxHeight: number): CameraFraming => {
  const aspect = boxWidth / boxHeight;
  const keyframes = (recording.camera ?? wholePageCamera(recording.pageRect)).map((keyframe) => ({
    at: keyframe.at,
    ...clampFraming(keyframe, recording.pageRect, aspect),
  }));
  return clampFraming(interpolateCamera(keyframes, seconds), recording.pageRect, aspect);
};

// Converts a source point to box coordinates for a framing.
export const sourcePointInBox = (framing: CameraFraming, boxWidth: number, boxHeight: number, sourceX: number, sourceY: number) => {
  const scale = boxWidth / framing.width;
  const visibleHeight = boxHeight / scale;
  return {
    x: (sourceX - (framing.centerX - framing.width / 2)) * scale,
    y: (sourceY - (framing.centerY - visibleHeight / 2)) * scale,
    scale,
  };
};

// The scene second at which a real click happens.
export const clickSceneSeconds = (recording: Recording, click: RealClick) =>
  "sceneTime" in click
    ? click.sceneTime
    : recording.media.kind === "video"
      ? outputSecondsAtSourceTime(recording.media.segments, click.sourceTime)
      : 0;

const VIDEO_STYLE: React.CSSProperties = { width: "100%", height: "100%", objectFit: "fill" };

// Plays the segments back to back, then holds the last frame, so a scene that is still on screen
// during a push never runs out of picture.
const SegmentedVideo: React.FC<{ src: string; segments: ClipSegment[] }> = ({ src, segments }) => {
  const lastSegment = segments[segments.length - 1];
  const lastSourceSeconds = "holdSeconds" in lastSegment ? lastSegment.start : lastSegment.end - 1 / FPS;
  const withTrailingHold: ClipSegment[] = [...segments, { start: lastSourceSeconds, holdSeconds: 600 }];
  let fromFrame = 0;
  return (
    <>
      {withTrailingHold.map((segment, index) => {
        const durationInFrames = Math.max(1, Math.round(segmentOutputSeconds(segment) * FPS));
        const sequenceStart = fromFrame;
        fromFrame += durationInFrames;
        const trimBefore = Math.round(segment.start * FPS);
        return (
          <Sequence key={index} from={sequenceStart} durationInFrames={durationInFrames} layout="none">
            {"holdSeconds" in segment ? (
              <Freeze frame={0}>
                <OffthreadVideo src={staticFile(src)} trimBefore={trimBefore} muted transparent style={VIDEO_STYLE} />
              </Freeze>
            ) : (
              <OffthreadVideo src={staticFile(src)} trimBefore={trimBefore} playbackRate={segment.speed} muted transparent style={VIDEO_STYLE} />
            )}
          </Sequence>
        );
      })}
    </>
  );
};

const StillSequence: React.FC<{ frames: { from: number; src: string }[] }> = ({ frames }) => {
  const seconds = useCurrentFrame() / FPS;
  const current = [...frames].reverse().find((still) => seconds >= still.from) ?? frames[0];
  return <Img src={staticFile(current.src)} style={{ width: "100%", height: "100%" }} />;
};

export const RecordingMediaView: React.FC<{ media: RecordingMedia }> = ({ media }) =>
  media.kind === "video" ? <SegmentedVideo src={media.src} segments={media.segments} /> : <StillSequence frames={media.frames} />;

// A recording filling a box through its camera. Children are overlays in box coordinates.
export const RecordingView: React.FC<{
  recording: Recording;
  boxWidth: number;
  boxHeight: number;
  children?: React.ReactNode;
}> = ({ recording, boxWidth, boxHeight, children }) => {
  const seconds = useCurrentFrame() / FPS;
  const framing = recordingFramingAt(recording, seconds, boxWidth, boxHeight);
  const origin = sourcePointInBox(framing, boxWidth, boxHeight, 0, 0);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: boxWidth, height: boxHeight, overflow: "hidden", background: "#fff" }}>
      <div
        style={{
          position: "absolute",
          left: origin.x,
          top: origin.y,
          width: recording.sourceSize.width,
          height: recording.sourceSize.height,
          transform: `scale(${origin.scale})`,
          transformOrigin: "0 0",
        }}
      >
        <RecordingMediaView media={recording.media} />
      </div>
      {children}
    </div>
  );
};

// One frozen source frame, cropped to `rect` and scaled to `width` (e.g. a formula lifted off a slide).
export const FrozenSourceRegion: React.FC<{
  src: string;
  sourceSize: { width: number; height: number };
  sourceSeconds: number;
  rect: SourceRect;
  width: number;
}> = ({ src, sourceSize, sourceSeconds, rect, width }) => {
  const scale = width / rect.width;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          left: -rect.x * scale,
          top: -rect.y * scale,
          width: sourceSize.width,
          height: sourceSize.height,
          transform: `scale(${scale})`,
          transformOrigin: "0 0",
        }}
      >
        <Freeze frame={0}>
          <OffthreadVideo src={staticFile(src)} trimBefore={Math.round(sourceSeconds * FPS)} muted transparent style={VIDEO_STYLE} />
        </Freeze>
      </div>
    </div>
  );
};
