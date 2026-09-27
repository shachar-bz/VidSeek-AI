import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
import { ChipJumpTransition } from "./components/ChipJumpTransition";
import { SceneTransition } from "./components/SceneTransition";
import { EndCard, Reveal } from "./scenes/BrandScenes";
import { FindVideoMontage } from "./scenes/FindVideoMontage";
import { Callback, HookQuestion } from "./scenes/HookScenes";
import { ElevenLabsHook } from "./scenes/ElevenLabsHook";
import {
  AskAnythingScene,
  CommentsScene,
  FollowUpsScene,
  ItReadsScene,
  ItWatchesScene,
  JumpToMomentScene,
  LibraryScene,
} from "./scenes/ProductScenes";
import { SceneId, scenes, toFrames } from "./timeline";
import { Soundtrack } from "./Soundtrack";

const SCENE_OVERLAP_SECONDS = 0.3;

const SCENE_COMPONENTS: { id: SceneId; component: React.FC; enter?: boolean }[] = [
  { id: "hookFilm", component: ElevenLabsHook, enter: false },
  { id: "hookQuestion", component: HookQuestion },
  { id: "reveal", component: Reveal, enter: false },
  { id: "findVideo", component: FindVideoMontage },
  { id: "askAnything", component: AskAnythingScene },
  { id: "jumpToMoment", component: JumpToMomentScene },
  { id: "comments", component: CommentsScene },
  { id: "followUps", component: FollowUpsScene },
  { id: "itWatches", component: ItWatchesScene },
  { id: "itReads", component: ItReadsScene },
  { id: "library", component: LibraryScene },
  { id: "callback", component: Callback },
  { id: "endCard", component: EndCard },
];

const formatAdTimestamp = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

const CHIP_JUMP_SCENES: SceneId[] = ["askAnything", "jumpToMoment", "comments", "followUps", "itWatches", "itReads", "library"];

export const VidSeekPromo: React.FC = () => (
  <AbsoluteFill>
    <Background />
    {SCENE_COMPONENTS.map(({ id, component: SceneComponent, enter }) => {
      const { start, end } = scenes[id];
      const isLast = id === "endCard";
      const durationInFrames = toFrames(end - start + (isLast ? 0 : SCENE_OVERLAP_SECONDS));
      return (
        <Sequence key={id} from={toFrames(start)} durationInFrames={durationInFrames} name={id}>
          <SceneTransition durationInFrames={isLast ? durationInFrames + 30 : durationInFrames} enter={enter}>
            <SceneComponent />
          </SceneTransition>
        </Sequence>
      );
    })}
    {CHIP_JUMP_SCENES.map((id) => (
      <Sequence key={`jump-${id}`} from={toFrames(scenes[id].start - 0.2)} durationInFrames={toFrames(0.6)} name={`jump-${id}`}>
        <ChipJumpTransition label={formatAdTimestamp(scenes[id].start)} />
      </Sequence>
    ))}
    <Captions />
    <Soundtrack />
  </AbsoluteFill>
);
