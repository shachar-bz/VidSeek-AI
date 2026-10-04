import React from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
import { SceneTransition } from "./components/SceneTransition";
import { EndCard, Reveal } from "./scenes/BrandScenes";
import { ElevenLabsHook } from "./scenes/ElevenLabsHook";
import { HookQuestion } from "./scenes/HookScenes";
import { ProductSection } from "./scenes/ProductSection";
import { SceneId, scenes, toFrames } from "./timeline";
import { Soundtrack } from "./Soundtrack";

const HOOK_OVERLAP_SECONDS = 0.3;

// The opening (0–17 s) keeps its original slide-and-blur hand-offs.
const HOOK_SCENES: { id: SceneId; component: React.FC; enter: boolean }[] = [
  { id: "hookFilm", component: ElevenLabsHook, enter: false },
  { id: "hookQuestion", component: HookQuestion, enter: true },
];

// The logo leaves cleanly (no blur) in the reveal's last 0.3 s, before the product window rises in.
const REVEAL_EXIT_SECONDS = 0.3;
const CleanExit: React.FC<{ durationInFrames: number; exitFrames: number; children: React.ReactNode }> = ({
  durationInFrames,
  exitFrames,
  children,
}) => {
  const frame = useCurrentFrame();
  const exit = interpolate(frame, [durationInFrames - exitFrames, durationInFrames], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: 1 - exit, transform: `scale(${1 - exit * 0.06})` }}>{children}</AbsoluteFill>;
};

export const VidSeekPromo: React.FC = () => {
  const revealFrames = toFrames(scenes.reveal.end - scenes.reveal.start);
  return (
    <AbsoluteFill>
      <Background />
      {HOOK_SCENES.map(({ id, component: SceneComponent, enter }) => {
        const durationInFrames = toFrames(scenes[id].end - scenes[id].start + HOOK_OVERLAP_SECONDS);
        return (
          <Sequence key={id} from={toFrames(scenes[id].start)} durationInFrames={durationInFrames} name={id}>
            <SceneTransition durationInFrames={durationInFrames} enter={enter}>
              <SceneComponent />
            </SceneTransition>
          </Sequence>
        );
      })}
      <Sequence from={toFrames(scenes.reveal.start)} durationInFrames={revealFrames} name="reveal">
        <CleanExit durationInFrames={revealFrames} exitFrames={toFrames(REVEAL_EXIT_SECONDS)}>
          <Reveal />
        </CleanExit>
      </Sequence>
      <ProductSection />
      <Sequence from={toFrames(scenes.endCard.start)} durationInFrames={toFrames(scenes.endCard.end - scenes.endCard.start)} name="endCard">
        <EndCard />
      </Sequence>
      <Captions />
      <Soundtrack />
    </AbsoluteFill>
  );
};
