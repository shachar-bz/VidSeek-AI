import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, shadows } from "../theme";
import { AI_STILLS_AVAILABLE } from "../timeline";

// The hook: Alex tries three ways to learn and gets frustrated by each.
// When the AI stills of Alex exist they fill the frame, and the floating UI
// pieces sit on the right; until then the UI pieces carry the scene alone.

const AlexStill: React.FC<{ file: string; pushFrom?: number; pushTo?: number }> = ({ file, pushFrom = 1, pushTo = 1.035 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (!AI_STILLS_AVAILABLE) return null;
  const scale = interpolate(frame, [0, durationInFrames], [pushFrom, pushTo]);
  return (
    <AbsoluteFill>
      <Img src={staticFile(`stills/${file}`)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})` }} />
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(0,0,0,0) 35%, rgba(0,0,0,0.35) 100%)" }} />
    </AbsoluteFill>
  );
};

const floatingPosition = (centeredLeft: number, stillLeft: number) => (AI_STILLS_AVAILABLE ? stillLeft : centeredLeft);

const useEnter = (delaySeconds = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delaySeconds * fps, fps, config: { damping: 18, stiffness: 120 } });
};

const TextBars: React.FC<{ lines: number; width: number; seed: number; color?: string; height?: number; gap?: number }> = ({
  lines,
  width,
  seed,
  color = "#c9cbd8",
  height = 10,
  gap = 12,
}) => (
  <div style={{ display: "flex", flexDirection: "column", gap }}>
    {Array.from({ length: lines }, (_, index) => {
      const lengthFactor = 0.62 + (((index + 3) * 37 + seed * 11) % 38) / 100;
      return <div key={index} style={{ width: width * lengthFactor, height, borderRadius: height / 2, background: color }} />;
    })}
  </div>
);

const CinematicHook: React.FC<{file: string; eyebrow: string; title: string; detail: string}> = ({file, eyebrow, title, detail}) => {
  const enter = useEnter(0.25);
  return <AbsoluteFill>
    <AlexStill file={file} />
    <div style={{position: 'absolute', left: 1160, top: 290, width: 660, color: 'white', fontFamily: fonts.sans, opacity: enter, transform: `translateY(${(1-enter)*20}px)`, textShadow: '0 3px 24px rgba(0,0,0,0.5)'}}>
      <div style={{fontSize: 22, letterSpacing: 5, fontWeight: 600, color: '#b9c5ff', marginBottom: 24}}>{eyebrow}</div>
      <div style={{fontSize: 92, lineHeight: 1.05, letterSpacing: -3, fontWeight: 700, whiteSpace: 'pre-line'}}>{title}</div>
      <div style={{fontSize: 30, lineHeight: 1.45, marginTop: 26, color: '#e0e3ee'}}>{detail}</div>
    </div>
  </AbsoluteFill>;
};

export const HookBook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = useEnter(0.1);
  const pageNumber = Math.min(12, 1 + Math.floor((frame / fps) * 2.8));
  const flip = ((frame / fps) * 1.6) % 1;
  if (AI_STILLS_AVAILABLE) return <CinematicHook file="alex_book.png" eyebrow="TOO MUCH TO READ" title="900 pages." detail="One question." />;
  return (
    <AbsoluteFill>
      <AlexStill file="alex_book.png" />
      <div
        style={{
          position: "absolute",
          left: floatingPosition(430, 1080),
          top: floatingPosition(180, 250),
          transform: `perspective(1800px) rotateX(${22 - enter * 6}deg) rotateZ(-3deg) scale(${(AI_STILLS_AVAILABLE ? 0.66 : 1) * (0.9 + enter * 0.1)})`,
          transformOrigin: "top left",
          opacity: enter,
        }}
      >
        {/* A 900-page book: two open pages over a tall stack of page edges. */}
        <div style={{ position: "relative", width: 1060, height: 600 }}>
          {Array.from({ length: 26 }, (_, index) => (
            <div
              key={index}
              style={{
                position: "absolute",
                left: 10 + index * 0.6,
                top: 40 + index * 4.2,
                width: 1040,
                height: 520,
                borderRadius: 14,
                background: index % 2 ? "#f1ede4" : "#e8e2d4",
                boxShadow: "0 2px 0 rgba(0,0,0,0.04)",
              }}
            />
          ))}
          <div style={{ position: "absolute", left: 0, top: 0, width: 1060, height: 540, display: "flex", borderRadius: 14, overflow: "hidden", boxShadow: shadows.card }}>
            {[0, 1].map((side) => (
              <div key={side} style={{ flex: 1, background: "#fbf9f4", padding: "54px 48px", borderRight: side === 0 ? "2px solid #e6e0d2" : undefined }}>
                <div style={{ width: 240, height: 18, borderRadius: 9, background: "#9a9cab", marginBottom: 28 }} />
                <TextBars lines={15} width={420} seed={side + 1} />
              </div>
            ))}
          </div>
          <div
            style={{
              position: "absolute",
              left: 530,
              top: 0,
              width: 530,
              height: 540,
              background: "linear-gradient(90deg, #f4f0e7, #fbf9f4)",
              transformOrigin: "left center",
              transform: `rotateY(${-flip * 180}deg)`,
              opacity: flip < 0.95 ? 0.9 : 0,
              borderRadius: "0 14px 14px 0",
              boxShadow: "-10px 0 30px rgba(0,0,0,0.08)",
            }}
          />
        </div>
        <div
          style={{
            marginTop: 70,
            display: "inline-flex",
            gap: 14,
            alignItems: "baseline",
            padding: "14px 26px",
            borderRadius: 999,
            background: colors.white,
            boxShadow: shadows.card,
            fontFamily: fonts.sans,
            fontSize: 34,
            fontWeight: 700,
            color: colors.ink,
          }}
        >
          Page <span style={{ fontVariantNumeric: "tabular-nums", color: colors.cobalt }}>{pageNumber}</span>
          <span style={{ color: colors.inkMuted, fontWeight: 600 }}>of 900</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const HookChatbot: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = useEnter(0.05);
  const seconds = frame / fps;
  const scroll = Math.max(0, seconds - 0.8) * 260;
  const doubt = spring({ frame: frame - 2.6 * fps, fps, config: { damping: 10 } });
  if (AI_STILLS_AVAILABLE) return <CinematicHook file="alex_chatbot.png" eyebrow="TOO MUCH TO VERIFY" title="A wall of text." detail="But is it right?" />;
  return (
    <AbsoluteFill>
      <AlexStill file="alex_chatbot.png" />
      <div
        style={{
          position: "absolute",
          left: floatingPosition(560, 1130),
          top: floatingPosition(90, 150),
          width: 800,
          height: 860,
          borderRadius: 28,
          background: colors.white,
          boxShadow: shadows.floatingScreen,
          overflow: "hidden",
          fontFamily: fonts.sans,
          opacity: enter,
          transform: `perspective(1600px) rotateY(${-12 + enter * 6}deg) translateY(${(1 - enter) * 60}px) scale(${AI_STILLS_AVAILABLE ? 0.8 : 1})`,
          transformOrigin: "top left",
        }}
      >
        <div style={{ padding: "22px 30px", borderBottom: `1px solid ${colors.mistBorder}`, fontSize: 24, fontWeight: 700, color: colors.inkMuted }}>
          AI Chat
        </div>
        <div style={{ position: "absolute", top: 80, left: 0, right: 0, bottom: 90, overflow: "hidden" }}>
          <div style={{ transform: `translateY(${-scroll}px)`, padding: "26px 34px" }}>
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 26 }}>
              <div style={{ background: colors.cobalt, color: colors.white, padding: "16px 22px", borderRadius: 20, fontSize: 26, fontWeight: 600 }}>
                How are stars born?
              </div>
            </div>
            {Array.from({ length: 9 }, (_, paragraph) => (
              <div key={paragraph} style={{ marginBottom: 26 }}>
                <TextBars lines={6} width={700} seed={paragraph} color="#d3d5e1" height={12} gap={13} />
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 90,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "linear-gradient(0deg, #fff 60%, rgba(255,255,255,0))",
            fontSize: 21,
            fontWeight: 600,
            color: interpolate(seconds, [2.4, 2.8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) > 0.5 ? colors.warning : colors.inkMuted,
          }}
        >
          ⚠ AI can make mistakes. Check important info.
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: floatingPosition(1300, 1700),
          top: floatingPosition(120, 150),
          width: 110,
          height: 110,
          borderRadius: "50%",
          background: colors.white,
          boxShadow: shadows.card,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: fonts.sans,
          fontSize: 70,
          fontWeight: 800,
          color: colors.warning,
          transform: `scale(${doubt}) rotate(${(1 - doubt) * -30}deg)`,
        }}
      >
        ?
      </div>
    </AbsoluteFill>
  );
};

const formatClock = (totalSeconds: number) => {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};

export const HookVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = useEnter(0.05);
  const seconds = frame / fps;
  // Alex scrubs back and forth, never landing on the right part.
  const scrubPositions = [0.12, 0.62, 0.35, 0.81, 0.47, 0.22, 0.7, 0.55];
  const step = Math.min(scrubPositions.length - 1, Math.floor(seconds / 0.55));
  const within = (seconds % 0.55) / 0.55;
  const from = scrubPositions[Math.max(0, step - 1)];
  const to = scrubPositions[step];
  const playhead = from + (to - from) * Math.min(1, within * 2.2);
  const playerWidth = 1180;
  if (AI_STILLS_AVAILABLE) return <CinematicHook file="alex_video.png" eyebrow="TOO MUCH TO WATCH" title="Two hours." detail="Where is the part you need?" />;
  return (
    <AbsoluteFill>
      <AlexStill file="alex_video.png" />
      <div
        style={{
          position: "absolute",
          left: floatingPosition(370, 1010),
          top: floatingPosition(150, 260),
          width: playerWidth,
          opacity: enter,
          transform: `perspective(1800px) rotateX(${10 - enter * 6}deg) translateY(${(1 - enter) * 50}px) scale(${AI_STILLS_AVAILABLE ? 0.72 : 1})`,
          transformOrigin: "top left",
          fontFamily: fonts.sans,
        }}
      >
        <div style={{ position: "relative", width: playerWidth, height: 664, borderRadius: 26, overflow: "hidden", boxShadow: shadows.floatingScreen, background: "linear-gradient(135deg, #2b2f4a, #151726)" }}>
          <div style={{ position: "absolute", left: 40, top: 34, color: "rgba(255,255,255,0.85)", fontSize: 28, fontWeight: 700 }}>
            Full lecture · Part 1 of 1
          </div>
          <div style={{ position: "absolute", left: "50%", top: "44%", transform: "translate(-50%,-50%)", width: 120, height: 120, borderRadius: "50%", background: "rgba(255,255,255,0.14)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="46" height="46" viewBox="0 0 10 10"><path d="M2 1 L9 5 L2 9 Z" fill="white" /></svg>
          </div>
          <div style={{ position: "absolute", left: 40, right: 40, bottom: 44 }}>
            <div style={{ position: "relative", height: 10, borderRadius: 5, background: "rgba(255,255,255,0.25)" }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${playhead * 100}%`, borderRadius: 5, background: colors.cobalt }} />
              <div style={{ position: "absolute", top: -9, left: `calc(${playhead * 100}% - 14px)`, width: 28, height: 28, borderRadius: "50%", background: colors.white, boxShadow: "0 0 18px rgba(82,102,235,0.8)" }} />
              <div style={{ position: "absolute", bottom: 34, left: `calc(${playhead * 100}% - 110px)`, width: 220, height: 124, borderRadius: 12, background: "linear-gradient(135deg, #3d4266, #22253b)", border: "3px solid white", display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(255,255,255,0.7)", fontSize: 56, fontWeight: 800 }}>
                ?
              </div>
            </div>
            <div style={{ marginTop: 18, color: colors.white, fontSize: 28, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
              {formatClock(playhead * 8040)} <span style={{ opacity: 0.6 }}>/ 2:14:00</span>
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const HookQuestion: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words: { text: string; at: number; accent?: boolean }[] = [
    { text: "What", at: 0.2 },
    { text: "if", at: 0.4 },
    { text: "Alex", at: 0.55 },
    { text: "could", at: 0.75 },
    { text: "just…", at: 0.95 },
    { text: "ask", at: 1.75, accent: true },
    { text: "the", at: 1.95, accent: true },
    { text: "video?", at: 2.1, accent: true },
  ];
  return (
    <AbsoluteFill style={{ background: colors.white, alignItems: "center", justifyContent: "center" }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 28px", width: 1500, fontFamily: fonts.sans }}>
        {words.map((word) => {
          const pop = spring({ frame: frame - word.at * fps, fps, config: { damping: 15, stiffness: 160 } });
          return (
            <span
              key={word.text + word.at}
              style={{
                fontSize: 112,
                fontWeight: 800,
                letterSpacing: -3,
                color: word.accent ? colors.cobalt : colors.ink,
                opacity: pop,
                transform: `translateY(${(1 - pop) * 40}px)`,
                display: "inline-block",
              }}
            >
              {word.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// After the product: Alex, relieved, gets the answer in seconds and shuts the book.
export const Callback: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = frame / fps;
  const enter = useEnter(0.05);
  const close = interpolate(seconds, [1.5, 1.85], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const check = spring({ frame: frame - 0.5 * fps, fps, config: { damping: 11 } });
  return (
    <AbsoluteFill>
      <AlexStill file="alex_relieved.png" pushFrom={1.035} pushTo={1} />
      {!AI_STILLS_AVAILABLE && (
        <div style={{ position: "absolute", left: 360, top: 380, width: 620, height: 380, perspective: 1600 }}>
          {Array.from({ length: 22 }, (_, index) => (
            <div key={index} style={{ position: "absolute", left: index * 0.5, top: 30 + index * 4, width: 600, height: 320, borderRadius: 12, background: index % 2 ? "#f1ede4" : "#e8e2d4" }} />
          ))}
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: 600,
              height: 330,
              borderRadius: 12,
              background: colors.cobalt,
              transformOrigin: "left center",
              transform: `rotateY(${(1 - close) * -150}deg)`,
              backfaceVisibility: "hidden",
              boxShadow: shadows.card,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: colors.white,
              fontFamily: fonts.sans,
              fontSize: 40,
              fontWeight: 800,
              letterSpacing: 4,
            }}
          >
            ASTRONOMY
          </div>
        </div>
      )}
      <div
        style={{
          position: "absolute",
          left: AI_STILLS_AVAILABLE ? 1180 : 1080,
          top: AI_STILLS_AVAILABLE ? 330 : 420,
          padding: "28px 36px",
          borderRadius: 26,
          background: colors.white,
          boxShadow: shadows.card,
          fontFamily: fonts.sans,
          opacity: enter,
          transform: `translateY(${(1 - enter) * 40}px)`,
          display: "flex",
          alignItems: "center",
          gap: 22,
        }}
      >
        <div style={{ width: 70, height: 70, borderRadius: "50%", background: colors.cobalt, display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${check})` }}>
          <svg width="38" height="38" viewBox="0 0 24 24"><path d="M5 12.5 L10 17.5 L19 7" stroke="white" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <div>
          <div style={{ fontSize: 36, fontWeight: 800, color: colors.ink }}>Got it.</div>
          <div style={{ fontSize: 24, fontWeight: 600, color: colors.inkMuted }}>Answer found in seconds</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
