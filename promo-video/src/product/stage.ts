import { Easing, interpolate, spring } from "remotion";
import { FPS, scenes, toFrames } from "../timeline";

// The product section is "one continuous window": a browser window that stays on screen
// from findVideo to the end of chatPins while its page content pushes sideways on the beat.

// Full-size window geometry, in composition pixels. The content area is exactly 16:9.
export const WINDOW = {
  left: 160,
  top: 76,
  width: 1600,
  barHeight: 36,
  contentWidth: 1600,
  contentHeight: 900,
  radius: 18,
} as const;
export const WINDOW_HEIGHT = WINDOW.barHeight + WINDOW.contentHeight;
const WINDOW_CENTER = { x: WINDOW.left + WINDOW.width / 2, y: WINDOW.top + WINDOW_HEIGHT / 2 };

// The headline sits above the window, aligned with its left edge.
export const HEADLINE = { fontSize: 44, lineHeight: 54, gapAboveWindow: 4 } as const;

// While the supported sites play, the window is pulled back to leave room for the site chips.
const MONTAGE_WINDOW = { scale: 0.82, top: 100 };
const montageTranslateY = MONTAGE_WINDOW.top - (WINDOW_CENTER.y - (WINDOW_HEIGHT / 2) * MONTAGE_WINDOW.scale);

export const SECTION_START = scenes.findVideo.start;
export const SECTION_END = scenes.chatPins.end;
const EXIT = { start: SECTION_END - 0.1, end: SECTION_END + 0.3 };
export const SECTION_RENDER_END = EXIT.end;

// Strong ease-in-out for every push, so the move reads as one decisive swipe.
export const pushEasing = Easing.bezier(0.7, 0, 0.3, 1);
const cameraEasing = Easing.bezier(0.65, 0, 0.35, 1);

// A push is centered on a boundary frame: half before it, half after it.
export type Push = { boundaryFrame: number; durationInFrames: number };
export const pushWindow = (push: Push) => ({
  from: push.boundaryFrame - Math.floor(push.durationInFrames / 2),
  to: push.boundaryFrame + Math.ceil(push.durationInFrames / 2),
});
// 0 before the push, 1 after it, eased in between.
export const pushProgress = (push: Push, frame: number) => {
  const { from, to } = pushWindow(push);
  return interpolate(frame, [from, to], [0, 1], { easing: pushEasing, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
};
// 0 → 1 → 0 across the push with zero velocity at both ends.
const pushBump = (push: Push, frame: number) => {
  const { from, to } = pushWindow(push);
  if (frame <= from || frame >= to) return 0;
  const linear = (frame - from) / (to - from);
  return (1 - Math.cos(2 * Math.PI * linear)) / 2;
};

const ENTRANCE_RISE = 960; // px: the pulled-back window starts with its top edge below the frame

export type WindowTransform = { scale: number; translateX: number; translateY: number; opacity: number };

// The window "camera" at a composition frame: entrance, montage pull-back, scale dips on
// every push, the push up to full size when the demos start, and the exit into the end card.
export const windowTransformAt = (
  frame: number,
  pushes: { montage: Push[]; product: Push[]; growToFullSize: Push },
): WindowTransform => {
  const seconds = frame / FPS;
  const entrance = spring({ frame: frame - toFrames(SECTION_START), fps: FPS, config: { damping: 18, stiffness: 110, mass: 0.9 } });
  const grow = interpolate(
    frame,
    [pushWindow(pushes.growToFullSize).from - 3, pushWindow(pushes.growToFullSize).to + 6],
    [0, 1],
    { easing: cameraEasing, extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const baseScale = interpolate(grow, [0, 1], [MONTAGE_WINDOW.scale, 1]);
  const baseTranslateY = interpolate(grow, [0, 1], [montageTranslateY, 0]);
  const montageDip = Math.max(0, ...pushes.montage.map((push) => pushBump(push, frame))) * 0.025;
  const productDip = Math.max(0, ...pushes.product.map((push) => pushBump(push, frame))) * 0.05;
  const exit = interpolate(seconds, [EXIT.start, EXIT.end], [0, 1], {
    easing: Easing.in(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return {
    scale: baseScale * interpolate(entrance, [0, 1], [0.92, 1]) * (1 - montageDip - productDip) * (1 - exit * 0.14),
    translateX: 0,
    // Rises from just below the frame, fully opaque, so it covers the outgoing logo instead of
    // double-exposing it.
    translateY: baseTranslateY + (1 - entrance) * ENTRANCE_RISE,
    opacity: 1 - exit,
  };
};

// Where the transformed window sits on screen.
export const windowRectFor = (transform: WindowTransform) => {
  const width = WINDOW.width * transform.scale;
  const height = WINDOW_HEIGHT * transform.scale;
  const centerX = WINDOW_CENTER.x + transform.translateX;
  const centerY = WINDOW_CENTER.y + transform.translateY;
  return { left: centerX - width / 2, top: centerY - height / 2, width, height, bottom: centerY + height / 2 };
};

export const windowCssTransform = (transform: WindowTransform) =>
  `translate(${transform.translateX}px, ${transform.translateY}px) scale(${transform.scale})`;

export const WINDOW_TRANSFORM_ORIGIN = `${WINDOW.width / 2}px ${WINDOW_HEIGHT / 2}px`;

// Headline wipe timing at the section's start and end.
export const HEADLINE_ENTRANCE: Push = { boundaryFrame: toFrames(SECTION_START + 0.45), durationInFrames: 12 };
export const HEADLINE_EXIT: Push = { boundaryFrame: toFrames(EXIT.start + 0.15), durationInFrames: 10 };
