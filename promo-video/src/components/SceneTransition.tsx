import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Scenes slide in from the right with a motion blur and fade out as the next one arrives.
export const SceneTransition: React.FC<{ durationInFrames: number; children: React.ReactNode; enter?: boolean }> = ({
  durationInFrames,
  children,
  enter = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enterFrames = Math.round(0.4 * fps);
  const exitFrames = Math.round(0.3 * fps);
  const enterProgress = enter ? interpolate(frame, [0, enterFrames], [0, 1], { extrapolateRight: "clamp" }) : 1;
  const easedEnter = 1 - Math.pow(1 - enterProgress, 3);
  const exitProgress = interpolate(frame, [durationInFrames - exitFrames, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      style={{
        opacity: easedEnter * (1 - exitProgress),
        transform: `translateX(${(1 - easedEnter) * 260 - exitProgress * 200}px) scale(${1 - exitProgress * 0.04})`,
        filter: `blur(${(1 - easedEnter) * 14 + exitProgress * 10}px)`,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
