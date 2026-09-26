import React from "react";
import { colors, fonts } from "../theme";

// The citation pill style used by VidSeek answers, e.g. 08:39–08:44.
export const TimestampChip: React.FC<{ label: string; scale?: number; glow?: number; style?: React.CSSProperties }> = ({
  label,
  scale = 1,
  glow = 0,
  style,
}) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 8 * scale,
      padding: `${6 * scale}px ${14 * scale}px`,
      borderRadius: 999,
      background: colors.cobaltSoft,
      color: colors.cobalt,
      fontFamily: fonts.sans,
      fontWeight: 700,
      fontSize: 22 * scale,
      fontVariantNumeric: "tabular-nums",
      boxShadow: `0 0 ${40 * glow}px rgba(82,102,235,${0.6 * glow})`,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    <svg width={14 * scale} height={14 * scale} viewBox="0 0 10 10">
      <path d="M2 1 L9 5 L2 9 Z" fill={colors.cobalt} />
    </svg>
    {label}
  </span>
);
