import React from "react";
import { Img, staticFile } from "remotion";
import type { AddressLabel } from "../product/recordings";
import { WINDOW, WINDOW_HEIGHT, WINDOW_TRANSFORM_ORIGIN, WindowTransform, windowCssTransform } from "../product/stage";
import { colors, fonts, shadows } from "../theme";

const TRAFFIC_LIGHTS = ["#f2a39b", "#f5d38f", "#a7d99d"]; // muted macOS close / minimize / zoom
const ADDRESS_PILL = { width: 380, height: 24 };

const AddressText: React.FC<{ label: AddressLabel }> = ({ label }) =>
  label.kind === "vidseek" ? (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, color: colors.ink, fontWeight: 600 }}>
      <Img src={staticFile("brand/vidseek-icon.png")} style={{ width: 16, height: 16, mixBlendMode: "multiply" }} />
      VidSeek AI
    </span>
  ) : (
    <span style={{ color: colors.inkMuted, fontWeight: 500 }}>{label.domain}</span>
  );

const sameLabel = (a: AddressLabel, b: AddressLabel) =>
  a.kind === b.kind && (a.kind === "vidseek" || (b.kind === "site" && a.domain === b.domain));

// The swap: the old label slides up out of the pill as the new one slides up into it.
const AddressPill: React.FC<{ from: AddressLabel; to: AddressLabel; progress: number }> = ({ from, to, progress }) => {
  const swapping = !sameLabel(from, to) && progress > 0 && progress < 1;
  const shown = progress >= 1 ? to : from;
  const line = (label: AddressLabel, offset: number) => (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transform: `translateY(${offset * ADDRESS_PILL.height}px)`,
      }}
    >
      <AddressText label={label} />
    </div>
  );
  return (
    <div
      style={{
        position: "absolute",
        left: (WINDOW.width - ADDRESS_PILL.width) / 2,
        top: (WINDOW.barHeight - ADDRESS_PILL.height) / 2,
        width: ADDRESS_PILL.width,
        height: ADDRESS_PILL.height,
        borderRadius: ADDRESS_PILL.height / 2,
        background: "#eff0f6",
        overflow: "hidden",
        fontFamily: fonts.sans,
        fontSize: 14,
        letterSpacing: 0.1,
      }}
    >
      {swapping ? (
        <>
          {line(from, -progress)}
          {line(to, 1 - progress)}
        </>
      ) : (
        line(shown, 0)
      )}
    </div>
  );
};

// A macOS-style browser window: slim top bar with muted traffic lights and a centered address pill,
// and a 16:9 content area. Children render inside the content area (1600×900, clipped).
export const ProductWindow: React.FC<{
  transform: WindowTransform;
  address: { from: AddressLabel; to: AddressLabel; progress: number };
  children: React.ReactNode;
}> = ({ transform, address, children }) => (
  <div
    style={{
      position: "absolute",
      left: WINDOW.left,
      top: WINDOW.top,
      width: WINDOW.width,
      height: WINDOW_HEIGHT,
      borderRadius: WINDOW.radius,
      overflow: "hidden",
      background: colors.white,
      boxShadow: shadows.floatingScreen,
      transform: windowCssTransform(transform),
      transformOrigin: WINDOW_TRANSFORM_ORIGIN,
      opacity: transform.opacity,
    }}
  >
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: WINDOW.width,
        height: WINDOW.barHeight,
        background: "#fafbfd",
        borderBottom: `1px solid ${colors.mistBorder}`,
        boxSizing: "border-box",
      }}
    >
      {TRAFFIC_LIGHTS.map((color, index) => (
        <div
          key={color}
          style={{ position: "absolute", left: 18 + index * 20, top: WINDOW.barHeight / 2 - 6, width: 12, height: 12, borderRadius: "50%", background: color }}
        />
      ))}
      <AddressPill {...address} />
    </div>
    <div
      style={{
        position: "absolute",
        left: 0,
        top: WINDOW.barHeight,
        width: WINDOW.contentWidth,
        height: WINDOW.contentHeight,
        overflow: "hidden",
        background: colors.white,
      }}
    >
      {children}
    </div>
  </div>
);
