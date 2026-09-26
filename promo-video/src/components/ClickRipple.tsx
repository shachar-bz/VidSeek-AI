import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";

// A cobalt ring that bursts where a real click happened. Times are scene-local seconds.
export const ClickRipple: React.FC<{ x: number; y: number; at: number; size?: number }> = ({ x, y, at, size = 90 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = interpolate(frame / fps, [at, at + 0.55], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (progress <= 0 || progress >= 1) return null;
  const diameter = size * (0.3 + progress);
  return (
    <div
      style={{
        position: "absolute",
        left: x - diameter / 2,
        top: y - diameter / 2,
        width: diameter,
        height: diameter,
        borderRadius: "50%",
        border: `${5 * (1 - progress) + 1}px solid ${colors.cobalt}`,
        background: `rgba(82,102,235,${0.18 * (1 - progress)})`,
        opacity: 1 - progress * 0.6,
      }}
    />
  );
};
