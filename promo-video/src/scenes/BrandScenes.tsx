import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts } from "../theme";
import { TimestampChip } from "../components/TimestampChip";

const Logo: React.FC<{ size: number }> = ({ size }) => (
  <Img src={staticFile("brand/vidseek-icon.png")} style={{ width: size, height: size, mixBlendMode: "multiply" }} />
);

// The drop: the logo punches in with a cobalt shockwave.
export const Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const punch = spring({ frame, fps, config: { damping: 9, stiffness: 170, mass: 0.8 } });
  const wordmark = spring({ frame: frame - 0.35 * fps, fps, config: { damping: 16 } });
  const ring = interpolate(frame, [0, 0.8 * fps], [0, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          position: "absolute",
          width: 300 + ring * 1500,
          height: 300 + ring * 1500,
          borderRadius: "50%",
          border: `${10 * (1 - ring) + 1}px solid ${colors.cobalt}`,
          opacity: 1 - ring,
        }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 36, fontFamily: fonts.sans }}>
        <div style={{ transform: `scale(${interpolate(punch, [0, 1], [2.4, 1])})`, opacity: Math.min(1, punch * 2) }}>
          <Logo size={220} />
        </div>
        <div
          style={{
            fontSize: 150,
            fontWeight: 800,
            letterSpacing: -5,
            color: colors.ink,
            opacity: wordmark,
            transform: `translateX(${(1 - wordmark) * -60}px)`,
            clipPath: `inset(0 ${(1 - wordmark) * 100}% 0 0)`,
          }}
        >
          VidSeek <span style={{ color: colors.cobalt }}>AI</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// Final card: logo, tagline and the maker's name.
export const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logo = spring({ frame: frame - 0.2 * fps, fps, config: { damping: 14 } });
  const tagline = spring({ frame: frame - 1.0 * fps, fps, config: { damping: 16 } });
  const byline = spring({ frame: frame - 2.4 * fps, fps, config: { damping: 18 } });
  const floatingChips = ["03:12", "07:33", "08:39", "21:41", "37:27"];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", fontFamily: fonts.sans }}>
      {floatingChips.map((label, index) => {
        const angle = (index / floatingChips.length) * Math.PI * 2 + frame / 220;
        const radiusX = 760;
        const radiusY = 380;
        return (
          <div
            key={label}
            style={{
              position: "absolute",
              left: 960 + Math.cos(angle) * radiusX - 80,
              top: 520 + Math.sin(angle) * radiusY - 20,
              opacity: 0.35 * logo,
            }}
          >
            <TimestampChip label={label} scale={1.1} />
          </div>
        );
      })}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 28, opacity: logo, transform: `scale(${interpolate(logo, [0, 1], [0.8, 1])})` }}>
          <Logo size={150} />
          <div style={{ fontSize: 112, fontWeight: 800, letterSpacing: -4, color: colors.ink }}>
            VidSeek <span style={{ color: colors.cobalt }}>AI</span>
          </div>
        </div>
        <div
          style={{
            marginTop: 30,
            fontSize: 64,
            fontWeight: 700,
            letterSpacing: -1.5,
            color: colors.ink,
            opacity: tagline,
            transform: `translateY(${(1 - tagline) * 30}px)`,
          }}
        >
          Ask any video <span style={{ color: colors.cobalt }}>anything.</span>
        </div>
        <div style={{ marginTop: 80, fontSize: 30, fontWeight: 600, color: colors.inkMuted, opacity: byline, letterSpacing: 0.5 }}>
          Built by <span style={{ color: colors.ink }}>Shachar Ben Zur</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
