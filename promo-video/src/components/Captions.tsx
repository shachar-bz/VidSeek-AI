import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors, fonts } from "../theme";
import { FPS, scenes, voiceoverCues, voiceoverDurations } from "../timeline";

const HIDDEN_DURING: { start: number; end: number }[] = [scenes.reveal, scenes.endCard];

// Burned-in narration captions so the ad works muted (LinkedIn autoplay).
export const Captions: React.FC = () => {
  const seconds = useCurrentFrame() / FPS;
  if (HIDDEN_DURING.some((range) => seconds >= range.start && seconds < range.end)) return null;
  const cue = voiceoverCues.find(
    (candidate) =>
      seconds >= candidate.start - 0.1 && seconds <= candidate.start + voiceoverDurations[candidate.id] + 0.25,
  );
  if (!cue) return null;
  const end = cue.start + voiceoverDurations[cue.id] + 0.25;
  const opacity = interpolate(seconds, [cue.start - 0.1, cue.start + 0.1, end - 0.2, end], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 34 }}>
      <div
        style={{
          opacity,
          maxWidth: 1400,
          padding: "12px 26px",
          borderRadius: 16,
          background: "rgba(255,255,255,0.88)",
          boxShadow: "0 8px 30px rgba(30,36,90,0.12)",
          fontFamily: fonts.sans,
          fontSize: 32,
          fontWeight: 500,
          color: colors.ink,
          textAlign: "center",
          lineHeight: 1.3,
        }}
      >
        {cue.caption}
      </div>
    </AbsoluteFill>
  );
};
