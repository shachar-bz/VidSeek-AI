import React from "react";
import { Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, shadows } from "../theme";
import { TimestampChip } from "./TimestampChip";

// A real sentence from the agent's answer, lifted out of the recording as a crisp floating card.
export const AnswerCard: React.FC<{
  text: string;
  chips?: string[];
  at: number;
  until: number;
  left: number;
  top: number;
  width?: number;
  label?: string;
}> = ({ text, chips = [], at, until, left, top, width = 560, label = "VidSeek" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  if (seconds < at - 0.05 || seconds > until + 0.4) return null;
  const enter = spring({ frame: frame - at * fps, fps, config: { damping: 16, stiffness: 140 } });
  const exit = interpolate(seconds, [until, until + 0.35], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        padding: "26px 30px",
        borderRadius: 24,
        background: "rgba(255,255,255,0.97)",
        boxShadow: shadows.card,
        borderLeft: `6px solid ${colors.cobalt}`,
        fontFamily: fonts.sans,
        opacity: enter * exit,
        transform: `perspective(1200px) translateY(${interpolate(enter, [0, 1], [50, 0])}px) rotateX(${interpolate(enter, [0, 1], [18, 0])}deg) scale(${interpolate(enter, [0, 1], [0.92, 1])})`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <Img src={staticFile("brand/vidseek-icon.png")} style={{ width: 30, height: 30, mixBlendMode: "multiply" }} />
        <span style={{ fontSize: 20, fontWeight: 700, color: colors.inkMuted, letterSpacing: 0.3 }}>{label}</span>
      </div>
      <div style={{ fontSize: 30, fontWeight: 600, color: colors.ink, lineHeight: 1.32 }}>{text}</div>
      {chips.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 18 }}>
          {chips.map((chip, index) => {
            const chipPop = spring({ frame: frame - (at + 0.35 + index * 0.12) * fps, fps, config: { damping: 12 } });
            return (
              <span key={chip + index} style={{ transform: `scale(${chipPop})`, display: "inline-block" }}>
                <TimestampChip label={chip} />
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
};
