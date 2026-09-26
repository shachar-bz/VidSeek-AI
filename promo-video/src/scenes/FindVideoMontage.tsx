import React from "react";
import { AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { ClipSegment, fullPageCamera, ScreenRecording } from "../components/ScreenRecording";
import { KineticWords } from "../components/KineticWords";

// Five real "Find video" / "Scan video" clicks on five different sites, each landing on a beat.
// `clickAt` is where the click happens in the source recording.
type SiteClip = { src: string; clickAt: number; playSeconds: number; leadIn?: number };

const SITE_CLIPS: SiteClip[] = [
  { src: "clips/youtube-login.mp4", clickAt: 0.233, playSeconds: 1.8 },
  { src: "clips/Internet_archive-login.mp4", clickAt: 0.6, playSeconds: 1.5 },
  { src: "clips/ted-login.mp4", clickAt: 37.57, playSeconds: 1.5 },
  { src: "clips/coursera-login.mp4", clickAt: 0.35, playSeconds: 0.75 },
  { src: "clips/moodle-login.mp4", clickAt: 0.3, playSeconds: 1.6 },
];

const CLICK_LEAD_SECONDS = 0.4; // each card arrives this long before its click
const FIRST_CLICK_SECONDS = 0.5; // scene-local; the scene starts half a beat before 20.0 s
const CLICK_SPACING_SECONDS = 1.0; // two beats
const SOURCE = { width: 1916, height: 1150 };
const CARD = { width: 1400, height: 840 };
// Keep the complete browser page and VidSeek side panel visible together.
const SIDE_PANEL_FRAMING = fullPageCamera(SOURCE.width, SOURCE.height, CARD.width, CARD.height);

const segmentsFor = (clip: SiteClip, visibleSeconds: number): ClipSegment[] => {
  const start = clip.clickAt - CLICK_LEAD_SECONDS;
  const segments: ClipSegment[] = [];
  if (start < 0) segments.push({ start: 0, holdSeconds: -start });
  const playStart = Math.max(0, start);
  const playEnd = playStart + clip.playSeconds;
  segments.push({ start: playStart, end: playEnd, speed: 1 });
  segments.push({ start: playEnd - 0.04, holdSeconds: Math.max(0.1, visibleSeconds) });
  return segments;
};

// Final resting slots: a gentle arc of five small cards.
const restingSlot = (index: number) => {
  const offset = index - 2;
  return { x: 960 + offset * 372, y: 360 + Math.abs(offset) * 28, rotate: offset * 3, scale: 0.34 };
};

export const FindVideoMontage: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const seconds = frame / fps;
  const settleAt = FIRST_CLICK_SECONDS + SITE_CLIPS.length * CLICK_SPACING_SECONDS - 0.2;
  const settle = spring({ frame: frame - settleAt * fps, fps, config: { damping: 18, stiffness: 110 } });
  return (
    <AbsoluteFill>
      {SITE_CLIPS.map((clip, index) => {
        const arriveAt = FIRST_CLICK_SECONDS + index * CLICK_SPACING_SECONDS - CLICK_LEAD_SECONDS;
        if (seconds < arriveAt - 0.05) return null;
        const arrive = spring({ frame: frame - arriveAt * fps, fps, config: { damping: 17, stiffness: 150 } });
        const nextArrive = arriveAt + CLICK_SPACING_SECONDS;
        const pushedBack = interpolate(seconds, [nextArrive, nextArrive + 0.3], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const isLast = index === SITE_CLIPS.length - 1;
        const slot = restingSlot(index);
        // While active: centered, full size. Once the next card comes: tuck back. At the end: arc slot.
        const activeX = 960 + (1 - arrive) * 1100;
        const activeRotateY = (1 - arrive) * -35;
        const tuckScale = 1 - (isLast ? 0 : pushedBack) * 0.12;
        const tuckOpacity = isLast ? 1 : 1 - pushedBack * 0.75;
        const centerX = interpolate(settle, [0, 1], [activeX, slot.x]);
        const centerY = interpolate(settle, [0, 1], [500, slot.y]);
        const scale = interpolate(settle, [0, 1], [tuckScale, slot.scale]);
        const opacity = interpolate(settle, [0, 1], [tuckOpacity, 1]);
        const clickSeconds = arriveAt + CLICK_LEAD_SECONDS;
        const clickFlash = interpolate(seconds, [clickSeconds, clickSeconds + 0.35], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const visibleSeconds = durationInFrames / fps - arriveAt;
        return (
          <div
            key={clip.src}
            style={{
              position: "absolute",
              left: centerX - CARD.width / 2,
              top: centerY - CARD.height / 2,
              width: CARD.width,
              height: CARD.height,
              opacity,
              transform: `perspective(2000px) rotateY(${activeRotateY + settle * slot.rotate}deg) scale(${scale})`,
              zIndex: index,
            }}
          >
            <SequenceFromArrival arriveAt={arriveAt}>
              <ScreenRecording
                src={clip.src}
                sourceWidth={SOURCE.width}
                sourceHeight={SOURCE.height}
                segments={segmentsFor(clip, visibleSeconds)}
                camera={SIDE_PANEL_FRAMING}
                boxWidth={CARD.width}
                boxHeight={CARD.height}
                borderRadius={26}
                style={{ outline: `${6 * clickFlash}px solid rgba(82,102,235,${clickFlash})` }}
              />
            </SequenceFromArrival>
          </div>
        );
      })}
      <KineticWords lines={["Almost any video.", "One click."]} at={settleAt + 0.3} until={8} left={0} top={600} width={1920} align="center" fontSize={96} />
    </AbsoluteFill>
  );
};

// Starts a card's recording at the moment the card arrives.
const SequenceFromArrival: React.FC<{ arriveAt: number; children: React.ReactNode }> = ({ arriveAt, children }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence from={Math.round(arriveAt * fps)} layout="none">
      {children}
    </Sequence>
  );
};
