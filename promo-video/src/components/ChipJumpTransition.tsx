import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { TimestampChip } from "./TimestampChip";

// The ad moves the way VidSeek does: between beats, a timestamp chip rides a
// scrubber streak across the screen, as if the ad itself jumped to the next moment.
export const ChipJumpTransition: React.FC<{ label: string }> = ({ label }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = interpolate(frame, [0, 0.55 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - progress, 3);
  const headX = interpolate(eased, [0, 1], [-300, 2220]);
  const opacity = interpolate(progress, [0, 0.1, 0.8, 1], [0, 1, 1, 0]);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity }}>
      <div
        style={{
          position: "absolute",
          top: 536,
          left: 0,
          width: Math.max(0, headX),
          height: 8,
          borderRadius: 4,
          background: `linear-gradient(90deg, rgba(82,102,235,0) 0%, ${colors.cobalt} 85%, #9aa8ff 100%)`,
        }}
      />
      <div style={{ position: "absolute", top: 510, left: headX - 90, filter: `blur(${(1 - progress) * 3}px)` }}>
        <TimestampChip label={label} scale={1.5} glow={1} />
      </div>
    </AbsoluteFill>
  );
};
