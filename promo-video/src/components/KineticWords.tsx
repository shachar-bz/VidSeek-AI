import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts } from "../theme";

// Big bold words that slam in on a beat; the last line is cobalt. Times are scene-local seconds.
export const KineticWords: React.FC<{
  lines: string[];
  at: number;
  until: number;
  left: number;
  top: number;
  fontSize?: number;
  align?: "left" | "center";
  width?: number;
}> = ({ lines, at, until, left, top, fontSize = 128, align = "left", width }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  if (seconds < at - 0.05 || seconds > until + 0.4) return null;
  const exit = interpolate(seconds, [until, until + 0.3], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left, top, width, textAlign: align, fontFamily: fonts.sans }}>
      {lines.map((line, index) => {
        const lineStart = (at + index * 0.18) * fps;
        const pop = spring({ frame: frame - lineStart, fps, config: { damping: 14, stiffness: 180, mass: 0.7 } });
        return (
          <div
            key={line}
            style={{
              fontSize,
              fontWeight: 800,
              letterSpacing: interpolate(pop, [0, 1], [18, -3]),
              lineHeight: 1.0,
              color: index === lines.length - 1 ? colors.cobalt : colors.ink,
              opacity: pop * exit,
              transform: `translateY(${interpolate(pop, [0, 1], [60, 0]) - (1 - exit) * 30}px) scale(${interpolate(pop, [0, 1], [1.25, 1])})`,
              transformOrigin: align === "left" ? "left center" : "center",
              whiteSpace: "nowrap",
            }}
          >
            {line}
          </div>
        );
      })}
    </div>
  );
};
