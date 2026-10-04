import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame } from "remotion";
import { ClickRipple } from "../components/ClickRipple";
import { clickSceneSeconds, FrozenSourceRegion, RecordingView, recordingFramingAt, sourcePointInBox } from "../components/RecordingView";
import { TimestampChip } from "../components/TimestampChip";
import { FindVideoTile, formulaLift, ProductSceneSource, productSceneSources, whiskReveal } from "../product/recordings";
import { WINDOW } from "../product/stage";
import { colors, fonts, shadows } from "../theme";
import { FPS } from "../timeline";

// Scene contents for the product window. Each one fills the window's content area
// (1600×900) and positions its overlays in content coordinates.
const W = WINDOW.contentWidth;
const H = WINDOW.contentHeight;
const SAFE = 48; // overlay margin from the content edges

const ClickRipples: React.FC<{ source: ProductSceneSource }> = ({ source }) => {
  const seconds = useCurrentFrame() / FPS;
  return (
    <>
      {(source.clicks ?? []).map((click) => {
        const at = clickSceneSeconds(source.recording, click);
        const framing = recordingFramingAt(source.recording, seconds, W, H);
        const point = sourcePointInBox(framing, W, H, click.sourceX, click.sourceY);
        return <ClickRipple key={at} x={point.x} y={point.y} at={at} size={100} />;
      })}
    </>
  );
};

// A recorded demonstration filling the window, with ripples at its real clicks.
export const RecordingScene: React.FC<{ source: ProductSceneSource; children?: React.ReactNode }> = ({ source, children }) => (
  <AbsoluteFill>
    <RecordingView recording={source.recording} boxWidth={W} boxHeight={H}>
      <ClickRipples source={source} />
    </RecordingView>
    {children}
  </AbsoluteFill>
);

export const AskAnythingContent: React.FC = () => <RecordingScene source={productSceneSources.askAnything} />;
export const JumpToMomentContent: React.FC = () => <RecordingScene source={productSceneSources.jumpToMoment} />;
export const CommentsContent: React.FC = () => <RecordingScene source={productSceneSources.comments} />;
export const FollowUpsContent: React.FC = () => <RecordingScene source={productSceneSources.followUps} />;
export const LibraryContent: React.FC = () => <RecordingScene source={productSceneSources.library} />;
export const ChatPinsContent: React.FC = () => <RecordingScene source={productSceneSources.chatPins} />;

export const FindVideoTileContent: React.FC<{ tile: FindVideoTile }> = ({ tile }) => {
  if (tile.chipLabel !== "Coursera") return <RecordingView recording={tile.recording} boxWidth={W} boxHeight={H} />;
  // Pair the lecture with its extension, excluding Coursera's unrelated audio popup.
  const lecture = { ...tile.recording, pageRect: { x: 0, y: 370, width: 2340, height: 1250 }, camera: [{ at: 0, centerX: 1700, centerY: 1040, width: 1280 }] };
  const panel = { ...tile.recording, pageRect: { x: 2342, y: 0, width: 540, height: 1620 }, camera: [{ at: 0, centerX: 2612, centerY: 660, width: 540 }] };
  return <AbsoluteFill>
    <div style={{ position: "absolute", left: 0, width: 1040, height: H, overflow: "hidden" }}><RecordingView recording={lecture} boxWidth={1040} boxHeight={H} /></div>
    <div style={{ position: "absolute", right: 0, width: 560, height: H, overflow: "hidden", borderLeft: "2px solid #e5e7eb" }}><RecordingView recording={panel} boxWidth={560} boxHeight={H} /></div>
  </AbsoluteFill>;
};

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const CornerBrackets: React.FC<{ opacity: number }> = ({ opacity }) => {
  const size = 64;
  const line = `5px solid ${colors.cobalt}`;
  const corners: React.CSSProperties[] = [
    { left: SAFE, top: SAFE, borderLeft: line, borderTop: line, borderTopLeftRadius: 10 },
    { right: SAFE, top: SAFE, borderRight: line, borderTop: line, borderTopRightRadius: 10 },
    { left: SAFE, bottom: SAFE, borderLeft: line, borderBottom: line, borderBottomLeftRadius: 10 },
    { right: SAFE, bottom: SAFE, borderRight: line, borderBottom: line, borderBottomRightRadius: 10 },
  ];
  return (
    <>
      {corners.map((corner, index) => (
        <div key={index} style={{ position: "absolute", width: size, height: size, opacity, ...corner }} />
      ))}
    </>
  );
};

// "It watches": the answer's chip lifts off, a circle opens from it into the real cooking footage.
const WhiskMomentReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const seconds = frame / FPS;
  const { revealAt } = whiskReveal;
  if (seconds < revealAt - 0.05) return null;
  const openAt = revealAt + 0.35;
  const sceneFraming = recordingFramingAt(productSceneSources.itWatches.recording, revealAt, W, H);
  const chipStart = sourcePointInBox(sceneFraming, W, H, whiskReveal.chipSource.x, whiskReveal.chipSource.y);
  const lift = spring({ frame: frame - revealAt * FPS, fps: FPS, config: { damping: 16, stiffness: 120 } });
  const open = interpolate(seconds, [openAt, openAt + 0.5], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const chipX = interpolate(lift, [0, 1], [chipStart.x, W / 2]);
  const chipY = interpolate(lift, [0, 1], [chipStart.y, H / 2]);
  const scan = ((seconds - openAt) % 1.2) / 1.2;
  const labelIn = spring({ frame: frame - (openAt + 0.3) * FPS, fps: FPS, config: { damping: 18, stiffness: 140 } });
  return (
    <>
      <div style={{ position: "absolute", inset: 0, clipPath: `circle(${open * Math.hypot(W, H)}px at ${chipX}px ${chipY}px)`, background: "#000" }}>
        <Sequence from={Math.round(openAt * FPS)} layout="none">
          <RecordingView recording={whiskReveal.footage} boxWidth={W} boxHeight={H} />
        </Sequence>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: `${Math.max(0, scan) * 100}%`,
            height: 3,
            background: "rgba(140,155,255,0.8)",
            boxShadow: "0 0 24px rgba(82,102,235,0.8)",
            opacity: open * 0.75,
          }}
        />
        <CornerBrackets opacity={open} />
        <div style={{ position: "absolute", left: SAFE + 28, top: SAFE + 26, opacity: open }}>
          <TimestampChip label={whiskReveal.momentLabel} scale={1.4} glow={0.5} style={{ background: "rgba(255,255,255,0.96)" }} />
        </div>
        <div
          style={{
            position: "absolute",
            left: SAFE + 28,
            bottom: SAFE + 26,
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "12px 28px 12px 14px",
            borderRadius: 999,
            background: "rgba(255,255,255,0.97)",
            boxShadow: shadows.card,
            fontFamily: fonts.sans,
            fontSize: 30,
            fontWeight: 700,
            color: colors.ink,
            whiteSpace: "nowrap",
            opacity: labelIn,
            transform: `translateY(${(1 - labelIn) * 24}px)`,
          }}
        >
          <Img src={staticFile("brand/vidseek-icon.png")} style={{ width: 40, height: 40, borderRadius: 10 }} />
          {whiskReveal.foundLabel}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: chipX,
          top: chipY,
          // Gone the moment the circle opens past the chip's own size, so it never ghosts over the footage.
          opacity: open > 0.04 ? 0 : 1,
          transform: `translate(-50%, -50%) scale(${1 + lift * 0.6})`,
        }}
      >
        <TimestampChip label={whiskReveal.chipLabel} scale={1.2} glow={lift} />
      </div>
    </>
  );
};

export const ItWatchesContent: React.FC = () => (
  <RecordingScene source={productSceneSources.itWatches}>
    <WhiskMomentReveal />
  </RecordingScene>
);

// "It reads": the formula lifts off the real slide and becomes a card above the cited answer.
const FORMULA_CARD_WIDTH = 946; // content px (2.6x a 1x recording: any larger and the slide text goes soft)
// White space the card adds above and below the cut-out (the slide has only a few px between the formula,
// the slide title and the grids), grown in during the lift so the card leaves the slide exactly in place.
const FORMULA_CARD_PADDING_Y = 16;
const FormulaLiftOff: React.FC = () => {
  const frame = useCurrentFrame();
  const seconds = frame / FPS;
  const { liftAt, rect } = formulaLift;
  if (seconds < liftAt - 0.05) return null;
  const recording = { ...productSceneSources.itReads.recording, pageRect: { x: 362, y: 335, width: 1106, height: 622 }, camera: undefined };
  if (recording.media.kind !== "video") return null;
  const lift = spring({ frame: frame - liftAt * FPS, fps: FPS, config: { damping: 15, stiffness: 90 } });
  const start = sourcePointInBox(recordingFramingAt(recording, liftAt, W, H), W, H, rect.x, rect.y);
  // The card's final width is fixed in content px, so a sharper (larger) recording needs less upscaling.
  const endScale = FORMULA_CARD_WIDTH / rect.width;
  const scale = interpolate(lift, [0, 1], [start.scale, endScale]);
  const width = rect.width * scale;
  const regionHeight = rect.height * scale;
  const paddingY = FORMULA_CARD_PADDING_Y * lift;
  // The slide's off-white melts into the card's white padding instead of leaving a seam.
  const fadePx = 6 * lift;
  const edgeFade = `linear-gradient(to bottom, transparent 0, #000 ${fadePx}px, #000 calc(100% - ${fadePx}px), transparent 100%)`;
  const height = regionHeight + paddingY * 2;
  const endLeft = (W - rect.width * endScale) / 2;
  const endTop = 112;
  const endCenterY = endTop + (rect.height * endScale) / 2 + FORMULA_CARD_PADDING_Y;
  const sparkle = interpolate(seconds, [liftAt, liftAt + 1.2], [0, 1], clamp);
  const caption = spring({ frame: frame - (liftAt + 0.7) * FPS, fps: FPS, config: { damping: 16 } });
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: `rgba(246,247,252,${0.84 * lift})` }} />
      <div
        style={{
          position: "absolute",
          left: interpolate(lift, [0, 1], [start.x, endLeft]),
          top: interpolate(lift, [0, 1], [start.y, endTop]),
          width,
          height,
          transform: `perspective(1400px) rotateX(${Math.sin(lift * Math.PI) * 22}deg) translateZ(${lift * 40}px)`,
          boxShadow: `0 ${30 * lift}px ${80 * lift}px rgba(30,36,90,${0.3 * lift}), 0 0 ${60 * sparkle}px rgba(82,102,235,${0.5 * (1 - sparkle) + 0.2})`,
          borderRadius: 12 * lift,
          overflow: "hidden",
          background: "#fff",
        }}
      >
        <div style={{ position: "absolute", left: 0, top: paddingY, width, height: regionHeight, maskImage: edgeFade, WebkitMaskImage: edgeFade, clipPath: "polygon(0 25%, 61% 25%, 61% 0, 100% 0, 100% 100%, 0 100%)" }}>
          <FrozenSourceRegion
            src={recording.media.src}
            sourceSize={recording.sourceSize}
            sourceSeconds={formulaLift.holdSourceTime}
            rect={rect}
            width={width}
          />
        </div>
      </div>
      {Array.from({ length: 14 }, (_, index) => {
        const angle = (index / 14) * Math.PI * 2;
        const distance = 120 + sparkle * 480;
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: W / 2 + Math.cos(angle) * distance * 1.3 - 5,
              top: endCenterY + Math.sin(angle) * distance * 0.45 - 5,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: colors.cobalt,
              opacity: (1 - sparkle) * lift,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: (W - 1200) / 2,
          width: 1200,
          top: 470,
          textAlign: "center",
          fontFamily: fonts.sans,
          opacity: caption,
          transform: `translateY(${(1 - caption) * 30}px)`,
        }}
      >
        <div style={{ fontSize: 26, fontWeight: 700, color: colors.cobalt, letterSpacing: 3, marginBottom: 16 }}>{formulaLift.citation}</div>
        <div
          style={{
            display: "inline-block",
            padding: "22px 34px",
            borderRadius: 22,
            background: colors.white,
            boxShadow: shadows.card,
            fontSize: 34,
            fontWeight: 600,
            color: colors.ink,
            lineHeight: 1.3,
          }}
        >
          {formulaLift.answer}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// The answer contains unrendered math. Cut past it and isolate the real timestamp
// as an editorial card, then show only the player; the answer is never readable.
export const ItReadsContent: React.FC = () => {
  const seconds = useCurrentFrame() / FPS;
  const recording = productSceneSources.itReads.recording;
  if (seconds >= 1.2 && seconds < 3.2) {
    const chipRecording = {
      ...recording,
      pageRect: { x: 1595, y: 939, width: 170, height: 42 },
      camera: undefined,
    };
    return <AbsoluteFill style={{ background: colors.canvas, alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: 680, height: 168, borderRadius: 24, overflow: "hidden", boxShadow: shadows.card }}>
        <RecordingView recording={chipRecording} boxWidth={680} boxHeight={168} />
      </div>
      <div style={{ marginTop: 28, fontFamily: fonts.sans, color: colors.cobalt, fontSize: 26, fontWeight: 700, letterSpacing: 3 }}>THE EXACT MOMENT</div>
    </AbsoluteFill>;
  }
  const framedRecording = seconds >= 3.2
    ? { ...recording, pageRect: { x: 362, y: 335, width: 1106, height: 622 }, camera: undefined }
    : recording;
  return <AbsoluteFill>
    <RecordingView recording={framedRecording} boxWidth={W} boxHeight={H} />
    <FormulaLiftOff />
  </AbsoluteFill>;
};
