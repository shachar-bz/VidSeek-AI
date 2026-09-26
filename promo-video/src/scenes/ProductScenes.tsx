import React from "react";
import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { AnswerCard } from "../components/AnswerCard";
import { ClickRipple } from "../components/ClickRipple";
import { KineticWords } from "../components/KineticWords";
import {
  CameraFrame,
  CameraKeyframe,
  ClipSegment,
  outputSecondsAtSourceTime,
  ScreenRecording,
  sourcePointToBox,
} from "../components/ScreenRecording";
import { TimestampChip } from "../components/TimestampChip";
import { colors, fonts, shadows } from "../theme";

// Layout shared by the product beats: messaging on the left, the real product floating on the right.
const BOX = { left: 610, top: 96, width: 1250, height: 703 };
const EXTENSION_SOURCE = { width: 1916, height: 1150 }; // Chrome window with the VidSeek side panel
const WEBSITE_SOURCE = { width: 1916, height: 1146 }; // VidSeek website video page

// Camera framings in source pixels.
const EXTENSION_WIDE = { centerX: 958, centerY: 616, width: 1880 };
const EXTENSION_INPUT = { centerX: 1516, centerY: 900, width: 800 };
const WEBSITE_WIDE = { centerX: 960, centerY: 600, width: 1420 };
const WEBSITE_CHAT = { centerX: 1110, centerY: 620, width: 760 };

type RealClick = { sourceTime: number; sourceX: number; sourceY: number };

type ProductExampleProps = {
  src: string;
  source: { width: number; height: number };
  segments: ClipSegment[];
  camera: CameraKeyframe[];
  kineticLines: string[];
  kineticUntil: number;
  kineticFontSize?: number;
  answers?: { text: string; chips?: string[]; at: number; until: number; label?: string }[];
  clicks?: RealClick[];
  children?: React.ReactNode;
};

// The floating screen drifts and tilts a little so the real UI feels three-dimensional.
const useFloatingTilt = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 20, stiffness: 90 } });
  return `perspective(2400px) rotateY(${-7 + enter * 3 + Math.sin(frame / 60) * 0.8}deg) rotateX(${2 - enter * 1}deg) translateY(${(1 - enter) * 30}px)`;
};

const ProductExample: React.FC<ProductExampleProps> = ({
  src,
  source,
  segments,
  camera,
  kineticLines,
  kineticUntil,
  kineticFontSize = 104,
  answers = [],
  clicks = [],
  children,
}) => {
  const transform = useFloatingTilt();
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: BOX.left, top: BOX.top, transform, transformOrigin: "center" }}>
        <ScreenRecording
          src={src}
          sourceWidth={source.width}
          sourceHeight={source.height}
          segments={segments}
          camera={camera}
          boxWidth={BOX.width}
          boxHeight={BOX.height}
        >
          {clicks.map((click) => {
            const at = outputSecondsAtSourceTime(segments, click.sourceTime);
            const point = sourcePointToBox(camera, at, BOX.width, BOX.height, click.sourceX, click.sourceY);
            return <ClickRipple key={click.sourceTime} x={point.x} y={point.y} at={at} size={110} />;
          })}
        </ScreenRecording>
      </div>
      <KineticWords lines={kineticLines} at={0.3} until={kineticUntil} left={60} top={120} fontSize={kineticFontSize} />
      {answers.map((answer) => (
        <AnswerCard key={answer.text} {...answer} left={48} top={440} width={570} />
      ))}
      {children}
    </AbsoluteFill>
  );
};

export const AskAnythingScene: React.FC = () => (
  <ProductExample
    src="clips/youtube_vid_question_a.mp4"
    source={EXTENSION_SOURCE}
    segments={[
      { start: 0, end: 15.2, speed: 8 },
      { start: 15.2, end: 15.6, speed: 1 },
      { start: 15.6, end: 24.8, speed: 8 },
      { start: 24.8, end: 26.8, speed: 1 },
      { start: 26.8, holdSeconds: 1.3 },
    ]}
    camera={[
      { at: 0, ...EXTENSION_WIDE },
      { at: 0.6, ...EXTENSION_INPUT },
      { at: 2.0, ...EXTENSION_INPUT },
      { at: 3.1, centerX: 1516, centerY: 420, width: 800 },
    ]}
    kineticLines={["ASK", "ANYTHING."]}
    kineticUntil={6.2}
    answers={[
      {
        text: "Trim obvious waste, then judge the result by the total work and rework, not just the prompt's token count.",
        chips: ["03:12–04:22", "04:24–05:16"],
        at: 3.9,
        until: 6.3,
      },
    ]}
  />
);

export const JumpToMomentScene: React.FC = () => (
  <ProductExample
    src="clips/coursera_questions_a.mp4"
    source={WEBSITE_SOURCE}
    segments={[
      { start: 1.6, end: 2.8, speed: 1 },
      { start: 2.8, end: 11.5, speed: 8 },
      { start: 11.5, end: 12.8, speed: 1 },
      { start: 13.6, end: 15.8, speed: 1 },
      { start: 15.8, holdSeconds: 0.6 },
    ]}
    camera={[
      { at: 0, ...WEBSITE_WIDE },
      { at: 0.5, ...WEBSITE_CHAT },
      { at: 3.3, ...WEBSITE_CHAT },
      { at: 3.9, centerX: 830, centerY: 520, width: 1150 },
    ]}
    kineticLines={["CLICK.", "JUMP."]}
    kineticUntil={5.7}
    answers={[
      {
        text: "The compiler produces VM code rather than translating Jack directly to machine code.",
        chips: ["07:33–09:27"],
        at: 2.4,
        until: 3.9,
      },
    ]}
    clicks={[{ sourceTime: 14.2, sourceX: 1191, sourceY: 699 }]}
  />
);

export const CommentsScene: React.FC = () => (
  <ProductExample
    src="clips/youtube_question_b.mp4"
    source={EXTENSION_SOURCE}
    segments={[
      { start: 0, end: 9.6, speed: 8 },
      { start: 9.6, end: 11, speed: 4 },
      { start: 11, end: 11.6, speed: 1 },
      { start: 11.6, end: 18.1, speed: 8 },
      { start: 18.1, end: 21.6, speed: 1 },
      { start: 21.6, holdSeconds: 0.4 },
    ]}
    camera={[
      { at: 0, ...EXTENSION_WIDE },
      { at: 0.5, ...EXTENSION_INPUT },
      { at: 2.2, ...EXTENSION_INPUT },
      { at: 3.0, centerX: 1516, centerY: 700, width: 800 },
    ]}
    kineticLines={["WHAT DO", "VIEWERS", "THINK?"]}
    kineticFontSize={88}
    kineticUntil={6.2}
    answers={[
      {
        text: "The top comments are mostly positive: several commenters praise the explanation, presentation, and channel.",
        at: 3.4,
        until: 6.3,
        label: "VidSeek · from the comments",
      },
    ]}
  />
);

const TED_SEGMENTS: ClipSegment[] = [
  // Question a: "what does Sam think about agents? are they advancing too fast?"
  { start: 7.0, end: 11.0, speed: 8 },
  { start: 11.0, end: 12.0, speed: 1 },
  { start: 12.2, end: 21.5, speed: 8 },
  { start: 21.5, end: 23.5, speed: 1 },
  // Follow-up b: "how can we limit the agents?" (the long wait and the layout reflow are cut)
  { start: 33.5, end: 37, speed: 8 },
  { start: 37, end: 37.8, speed: 1 },
  { start: 47, end: 48.6, speed: 8 },
  { start: 48.6, end: 49.8, speed: 1 },
  { start: 50, end: 53.6, speed: 6 },
  { start: 53.6, end: 55.7, speed: 1 },
  { start: 55.7, holdSeconds: 0.4 },
];

export const FollowUpsScene: React.FC = () => (
  <ProductExample
    src="clips/ted_questions_a_b.mp4"
    source={WEBSITE_SOURCE}
    segments={TED_SEGMENTS}
    camera={[
      { at: 0, ...WEBSITE_WIDE },
      { at: 0.5, centerX: 1150, centerY: 720, width: 900 },
      { at: 4.6, centerX: 1150, centerY: 720, width: 900 },
      { at: 5.1, centerX: 945, centerY: 640, width: 1480 },
    ]}
    kineticLines={["GO", "DEEPER."]}
    kineticUntil={9.7}
    answers={[
      {
        text: "For agents specifically, progress is constrained by the ability to make them safe and trustworthy.",
        chips: ["14:28–15:10", "21:41–24:37"],
        at: 3.0,
        until: 4.9,
      },
      {
        text: "Agents need to be trustworthy before people give them access to their systems and data.",
        chips: ["21:41–24:37", "24:37–25:48"],
        at: 6.9,
        until: 9.7,
        label: "VidSeek · follow-up",
      },
    ]}
    clicks={[{ sourceTime: 53.9, sourceX: 1382, sourceY: 874 }]}
  />
);

// "It watches": the visual agent finds the whisking, then we jump into the real moment at 08:39.
const WATCH_SEGMENTS: ClipSegment[] = [
  { start: 0, end: 2.4, speed: 2 },
  { start: 5.4, end: 6.4, speed: 1 }, // skips the typed-then-deleted " for how"
  { start: 6.4, end: 10.4, speed: 4 }, // "Looking at what the video shows..."
  { start: 50.4, end: 54.2, speed: 8 },
  { start: 54.2, end: 56.2, speed: 1 },
  { start: 56.2, holdSeconds: 3.2 },
];
const WATCH_CAMERA: CameraKeyframe[] = [
  { at: 0, ...EXTENSION_WIDE },
  { at: 0.4, ...EXTENSION_INPUT },
  { at: 2.0, ...EXTENSION_INPUT },
  { at: 2.6, centerX: 1516, centerY: 340, width: 800 },
];
const WHISK_CHIP_SOURCE = { x: 1716, y: 321 };
const WHISK_REVEAL_AT = 5.9;

const WhiskMomentReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  if (seconds < WHISK_REVEAL_AT - 0.05) return null;
  const chipStart = sourcePointToBox(WATCH_CAMERA, WHISK_REVEAL_AT, BOX.width, BOX.height, WHISK_CHIP_SOURCE.x, WHISK_CHIP_SOURCE.y);
  const lift = spring({ frame: frame - WHISK_REVEAL_AT * fps, fps, config: { damping: 16, stiffness: 120 } });
  const open = interpolate(seconds, [WHISK_REVEAL_AT + 0.35, WHISK_REVEAL_AT + 0.85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const chipX = interpolate(lift, [0, 1], [chipStart.x, BOX.width / 2]);
  const chipY = interpolate(lift, [0, 1], [chipStart.y, BOX.height / 2]);
  const scan = ((seconds - WHISK_REVEAL_AT) % 1.2) / 1.2;
  return (
    <>
      <div
        style={{
          position: "absolute",
          inset: 0,
          clipPath: `circle(${open * 120}% at ${chipX}px ${chipY}px)`,
          background: "#000",
        }}
      >
        <Sequence from={Math.round((WHISK_REVEAL_AT + 0.35) * fps)} layout="none">
          <ScreenRecording
            src="clips/ia_whisk.mp4"
            segments={[{ start: 4.0, end: 7.2, speed: 1 }]}
            sourceWidth={1454}
            sourceHeight={1080}
            camera={[{ at: 0, centerX: 727, centerY: 540, width: 1454 }]}
            boxWidth={BOX.width}
            boxHeight={BOX.height}
            borderRadius={0}
            style={{ boxShadow: "none", background: "#000" }}
          />
        </Sequence>
        <div style={{ position: "absolute", left: 0, right: 0, top: `${scan * 100}%`, height: 4, background: "rgba(120,140,255,0.85)", boxShadow: "0 0 30px rgba(82,102,235,0.9)", opacity: open }} />
        {[
          { left: 60, top: 60, borders: "borderLeft borderTop" },
          { right: 60, top: 60, borders: "borderRight borderTop" },
          { left: 60, bottom: 60, borders: "borderLeft borderBottom" },
          { right: 60, bottom: 60, borders: "borderRight borderBottom" },
        ].map((corner, index) => {
          const { borders, ...position } = corner;
          const style: React.CSSProperties = { position: "absolute", width: 70, height: 70, opacity: open, ...position };
          for (const border of borders.split(" ")) (style as Record<string, string>)[border] = `6px solid ${colors.cobalt}`;
          return <div key={index} style={style} />;
        })}
        <div
          style={{
            position: "absolute",
            left: 60,
            bottom: 150,
            opacity: open,
            padding: "12px 22px",
            borderRadius: 14,
            background: "rgba(255,255,255,0.94)",
            fontFamily: fonts.sans,
            fontSize: 30,
            fontWeight: 700,
            color: colors.ink,
          }}
        >
          Found it: whisking the eggs
        </div>
      </div>
      <div style={{ position: "absolute", left: chipX - 120, top: chipY - 30, opacity: 1 - open, transform: `scale(${1 + lift * 0.6})` }}>
        <TimestampChip label="08:39–08:44" scale={1.2} glow={lift} />
      </div>
      <div style={{ position: "absolute", left: 60, top: 60, opacity: open, transform: `scale(${0.8 + open * 0.2})`, transformOrigin: "left top" }}>
        <TimestampChip label="08:39" scale={1.5} glow={0.6} style={{ background: "rgba(255,255,255,0.95)" }} />
      </div>
    </>
  );
};

export const ItWatchesScene: React.FC = () => {
  const transform = useFloatingTilt();
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: BOX.left, top: BOX.top, transform }}>
        <ScreenRecording
          src="clips/Internet_archive_question_a.mp4"
          sourceWidth={EXTENSION_SOURCE.width}
          sourceHeight={1148}
          segments={WATCH_SEGMENTS}
          camera={WATCH_CAMERA}
          boxWidth={BOX.width}
          boxHeight={BOX.height}
        >
          <WhiskMomentReveal />
        </ScreenRecording>
      </div>
      <KineticWords lines={["IT", "WATCHES."]} at={0.3} until={8.2} left={60} top={120} fontSize={104} />
      <AnswerCard
        text="He whisks eggs for the custard around 08:39, and again for the pumpkin pie filling around 14:49."
        chips={["08:39–08:44", "14:49–15:04"]}
        at={3.9}
        until={5.8}
        left={48}
        top={440}
        width={570}
      />
    </AbsoluteFill>
  );
};

// "It reads": the answer cites the slide, and the formula lifts off the real slide.
const READ_SEGMENTS: ClipSegment[] = [
  { start: 2.0, end: 4.6, speed: 4 },
  { start: 4.6, end: 5.6, speed: 1 },
  { start: 5.8, end: 15.8, speed: 8 },
  { start: 15.8, end: 17.3, speed: 1 },
  { start: 21.0, end: 23.4, speed: 1 },
  { start: 23.4, end: 25.0, speed: 1 },
  { start: 25.0, holdSeconds: 3.0 },
];
const READ_CAMERA: CameraKeyframe[] = [
  { at: 0, ...WEBSITE_WIDE },
  { at: 0.4, ...WEBSITE_CHAT },
  { at: 4.4, ...WEBSITE_CHAT },
  { at: 5.0, centerX: 800, centerY: 520, width: 1100 },
  { at: 6.6, centerX: 800, centerY: 520, width: 1100 },
  { at: 7.6, centerX: 633, centerY: 420, width: 560 },
];
const SLIDE_FORMULA = { x: 452, y: 358, width: 340, height: 86 };
const LIFT_AT = 8.2;

const FormulaLiftOff: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  if (seconds < LIFT_AT - 0.05) return null;
  const lift = spring({ frame: frame - LIFT_AT * fps, fps, config: { damping: 15, stiffness: 90 } });
  const start = sourcePointToBox(READ_CAMERA, LIFT_AT, BOX.width, BOX.height, SLIDE_FORMULA.x, SLIDE_FORMULA.y);
  const startScale = start.scale;
  const endScale = 3.4;
  const scale = interpolate(lift, [0, 1], [startScale, endScale]);
  const width = SLIDE_FORMULA.width * scale;
  const height = SLIDE_FORMULA.height * scale;
  const startLeft = BOX.left + start.x;
  const startTop = BOX.top + start.y;
  const endLeft = 960 - (SLIDE_FORMULA.width * endScale) / 2;
  const endTop = 250;
  const sparkle = interpolate(seconds, [LIFT_AT, LIFT_AT + 1.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const caption = spring({ frame: frame - (LIFT_AT + 0.7) * fps, fps, config: { damping: 16 } });
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: `rgba(246,247,252,${0.75 * lift})` }} />
      <div
        style={{
          position: "absolute",
          left: interpolate(lift, [0, 1], [startLeft, endLeft]),
          top: interpolate(lift, [0, 1], [startTop, endTop]),
          width,
          height,
          transform: `perspective(1400px) rotateX(${Math.sin(lift * Math.PI) * 22}deg) translateZ(${lift * 40}px)`,
          boxShadow: `0 ${30 * lift}px ${80 * lift}px rgba(30,36,90,${0.3 * lift}), 0 0 ${60 * sparkle}px rgba(82,102,235,${0.5 * (1 - sparkle) + 0.2})`,
          borderRadius: 12 * lift,
          overflow: "hidden",
        }}
      >
        <CameraFrame
          sourceWidth={WEBSITE_SOURCE.width}
          sourceHeight={WEBSITE_SOURCE.height}
          camera={[{ at: 0, centerX: SLIDE_FORMULA.x + SLIDE_FORMULA.width / 2, centerY: SLIDE_FORMULA.y + SLIDE_FORMULA.height / 2, width: SLIDE_FORMULA.width }]}
          boxWidth={width}
          boxHeight={height}
          borderRadius={0}
          style={{ boxShadow: "none" }}
          content={<SlideFreezeFrame />}
        />
      </div>
      {Array.from({ length: 14 }, (_, index) => {
        const angle = (index / 14) * Math.PI * 2;
        const distance = 120 + sparkle * 520;
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: 960 + Math.cos(angle) * distance * 1.4,
              top: endTop + (SLIDE_FORMULA.height * endScale) / 2 + Math.sin(angle) * distance * 0.5,
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
          left: 360,
          width: 1200,
          top: 610,
          textAlign: "center",
          fontFamily: fonts.sans,
          opacity: caption,
          transform: `translateY(${(1 - caption) * 30}px)`,
        }}
      >
        <div style={{ fontSize: 26, fontWeight: 700, color: colors.cobalt, letterSpacing: 3, marginBottom: 14 }}>READ FROM THE SLIDE · 37:27</div>
        <div style={{ display: "inline-block", padding: "22px 34px", borderRadius: 22, background: colors.white, boxShadow: shadows.card, fontSize: 34, fontWeight: 600, color: colors.ink, lineHeight: 1.3 }}>
          The minimum seam cost to each pixel is its energy plus the cheapest of the three pixels above it.
        </div>
      </div>
    </AbsoluteFill>
  );
};

const SlideFreezeFrame: React.FC = () => (
  <ScreenRecording
    src="clips/moodle_question_a.mp4"
    segments={[{ start: 25.0, holdSeconds: 12 }]}
    sourceWidth={WEBSITE_SOURCE.width}
    sourceHeight={WEBSITE_SOURCE.height}
    camera={[{ at: 0, centerX: WEBSITE_SOURCE.width / 2, centerY: WEBSITE_SOURCE.height / 2, width: WEBSITE_SOURCE.width }]}
    boxWidth={WEBSITE_SOURCE.width}
    boxHeight={WEBSITE_SOURCE.height}
    borderRadius={0}
    style={{ boxShadow: "none" }}
  />
);

export const ItReadsScene: React.FC = () => (
  <AbsoluteFill>
    <ProductExample
      src="clips/moodle_question_a.mp4"
      source={WEBSITE_SOURCE}
      segments={READ_SEGMENTS}
      camera={READ_CAMERA}
      kineticLines={["IT", "READS."]}
      kineticUntil={7.9}
      answers={[
        {
          text: "The minimum seam cost to each pixel is its energy plus the cheapest of the three pixels above it.",
          chips: ["37:27–40:25", "40:26–41:59"],
          at: 2.9,
          until: 5.0,
        },
      ]}
      clicks={[{ sourceTime: 21.8, sourceX: 1161, sourceY: 699 }]}
    />
    <Sequence from={0} layout="none">
      <FormulaLiftOff />
    </Sequence>
  </AbsoluteFill>
);

// "Your library": the real library as Alex sees it, tagged, then filtered by the AI tag.
export const LibraryScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  const transform = useFloatingTilt();
  const filtered = interpolate(seconds, [3.2, 3.38], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const LIBRARY_SOURCE = { width: 3200, height: 1800 };
  const gridCamera: CameraKeyframe[] = [
    { at: 0, centerX: 1600, centerY: 900, width: 3200 },
    { at: 3.0, centerX: 1500, centerY: 820, width: 2700 },
  ];
  const filteredCamera: CameraKeyframe[] = [
    { at: 3.2, centerX: 1450, centerY: 760, width: 2500 },
    { at: 6.5, centerX: 1400, centerY: 820, width: 2750 },
  ];
  const tags = ["AI", "Cooking", "Lecture", "TED", "Computer Science", "LLMs", "Agents"];
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: BOX.left, top: BOX.top, transform }}>
        <CameraFrame
          sourceWidth={LIBRARY_SOURCE.width}
          sourceHeight={LIBRARY_SOURCE.height}
          camera={gridCamera}
          boxWidth={BOX.width}
          boxHeight={BOX.height}
          content={<LibraryImage file="stills/lib_grid_tagged.png" />}
        >
          <div style={{ position: "absolute", inset: 0, opacity: filtered }}>
            <CameraFrame
              sourceWidth={LIBRARY_SOURCE.width}
              sourceHeight={LIBRARY_SOURCE.height}
              camera={filteredCamera}
              boxWidth={BOX.width}
              boxHeight={BOX.height}
              borderRadius={0}
              style={{ boxShadow: "none" }}
              content={<LibraryImage file="stills/lib_grid_filter_ai.png" />}
            />
          </div>
        </CameraFrame>
      </div>
      <KineticWords lines={["YOUR", "LIBRARY."]} at={0.3} until={6.7} left={60} top={120} fontSize={104} />
      <div style={{ position: "absolute", left: 56, top: 440, width: 520, display: "flex", flexWrap: "wrap", gap: 14 }}>
        {tags.map((tag, index) => {
          const pop = spring({ frame: frame - (0.8 + index * 0.15) * fps, fps, config: { damping: 12 } });
          const selected = tag === "AI" ? interpolate(seconds, [2.6, 3.0], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
          return (
            <div
              key={tag}
              style={{
                transform: `translateY(${Math.sin(frame / 25 + index) * 3}px) scale(${pop * (1 + selected * 0.15)})`,
                padding: "12px 22px",
                borderRadius: 999,
                background: selected > 0.5 ? colors.cobalt : colors.white,
                color: selected > 0.5 ? colors.white : colors.ink,
                boxShadow: shadows.card,
                fontFamily: fonts.sans,
                fontSize: 26,
                fontWeight: 700,
                whiteSpace: "nowrap",
              }}
            >
              {tag}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const LibraryImage: React.FC<{ file: string }> = ({ file }) => (
  <Img src={staticFile(file)} style={{ width: 3200, height: 1800, display: "block" }} />
);
