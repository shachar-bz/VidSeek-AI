import React from "react";
import { HEADLINE } from "../product/stage";
import { colors, fonts } from "../theme";

// A one-line kinetic headline: ink lead words, cobalt accent words.
export type Headline = { lead: string; accent: string };

const MASK_HEIGHT = HEADLINE.lineHeight + 6;

const HeadlineLine: React.FC<{ headline: Headline; offset: number }> = ({ headline, offset }) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      top: 0,
      height: MASK_HEIGHT,
      display: "flex",
      alignItems: "center",
      gap: "0.26em",
      whiteSpace: "nowrap",
      fontFamily: fonts.sans,
      fontSize: HEADLINE.fontSize,
      fontWeight: 800,
      letterSpacing: -1.2,
      lineHeight: `${HEADLINE.lineHeight}px`,
      transform: `translateY(${offset * MASK_HEIGHT}px)`,
    }}
  >
    {headline.lead && <span style={{ color: colors.ink }}>{headline.lead}</span>}
    <span style={{ color: colors.cobalt }}>{headline.accent}</span>
  </div>
);

// Swaps headlines with a mask wipe: the old one wipes up and out while the new one wipes up and in.
// `progress` runs 0 → 1 in step with the content push. A null side is empty (entrance or exit).
export const HeadlineSwap: React.FC<{
  left: number;
  bottom: number;
  from: Headline | null;
  to: Headline | null;
  progress: number;
}> = ({ left, bottom, from, to, progress }) => {
  const settled = progress <= 0 ? from : progress >= 1 ? to : null;
  if (progress <= 0 && !from) return null;
  if (progress >= 1 && !to) return null;
  return (
    <div style={{ position: "absolute", left, top: bottom - MASK_HEIGHT, width: 1700, height: MASK_HEIGHT, overflow: "hidden" }}>
      {settled ? (
        <HeadlineLine headline={settled} offset={0} />
      ) : (
        <>
          {from && <HeadlineLine headline={from} offset={-progress} />}
          {to && <HeadlineLine headline={to} offset={1 - progress} />}
        </>
      )}
    </div>
  );
};
