import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { colors } from "../theme";

// Light canvas with slowly drifting cobalt glows and a faint dot grid.
export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = (speed: number, range: number, phase: number) => Math.sin(frame / speed + phase) * range;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(160deg, ${colors.canvas} 0%, ${colors.canvasDeep} 100%)` }}>
      <div
        style={{
          position: "absolute",
          width: 1100,
          height: 1100,
          left: 1100 + drift(140, 80, 0),
          top: -420 + drift(170, 60, 1),
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(82,102,235,0.20) 0%, rgba(82,102,235,0) 65%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 1000,
          height: 1000,
          left: -380 + drift(160, 70, 2),
          top: 380 + drift(130, 70, 3),
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(120,140,255,0.16) 0%, rgba(120,140,255,0) 65%)",
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage: "radial-gradient(rgba(23,23,33,0.07) 1.3px, transparent 1.3px)",
          backgroundSize: "34px 34px",
          backgroundPosition: `${(frame * 0.15) % 34}px 0px`,
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
        }}
      />
    </AbsoluteFill>
  );
};
