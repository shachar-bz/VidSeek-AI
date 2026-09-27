import React from "react";
import { Audio, interpolate, Sequence, staticFile } from "remotion";
import { FPS, MUSIC_DROP_SECONDS, scenes, SceneId, toFrames, TOTAL_DURATION_SECONDS, visualPlaybackRates, voiceoverCues, voiceoverDurations } from "./timeline";

type SoundEffectCue = { id: string; at: number; volume: number; duration?: number };

const sceneBoundaries = [
  scenes.askAnything.start,
  scenes.jumpToMoment.start,
  scenes.comments.start,
  scenes.followUps.start,
  scenes.itWatches.start,
  scenes.itReads.start,
  scenes.library.start,
  scenes.chatPins.start,
];

const moment = (scene: SceneId, local: number) => scenes[scene].start + local / (visualPlaybackRates[scene] ?? 1);

export const soundEffectCues: SoundEffectCue[] = [
  { id: "page_flip", at: 3.15, volume: 0.3, duration: 1.2 },
  { id: "keyboard_typing", at: 5.3, volume: 0.2, duration: 1.6 },
  { id: "riser", at: 14.5, volume: 0.35 },
  { id: "impact", at: MUSIC_DROP_SECONDS, volume: 0.32 },
  // Timestamp-jump transitions between product beats.
  ...sceneBoundaries.map((at) => ({ id: "soft_transition", at: at - 0.1, volume: 0.13, duration: 0.7 })),
  // Real clicks and answers landing inside the recordings.
  { id: "ui_pop", at: moment("askAnything", 3.45), volume: 0.45 },
  { id: "ui_click", at: moment("jumpToMoment", 4.19), volume: 0.6 },
  { id: "ui_pop", at: moment("comments", 3), volume: 0.45 },
  { id: "ui_pop", at: moment("followUps", 2.7), volume: 0.45 },
  { id: "ui_click", at: moment("followUps", 8.2), volume: 0.6 },
  { id: "ui_pop", at: moment("itWatches", 3.7), volume: 0.45 },
  { id: "soft_transition", at: moment("itWatches", 5.9), volume: 0.15, duration: 0.7 },
  { id: "ui_click", at: moment("itReads", 5.2), volume: 0.6 },
  { id: "shimmer", at: moment("itReads", 8.2), volume: 0.6 },
  { id: "impact", at: scenes.endCard.start + 0.2, volume: 0.35 },
];

// Smooth attack/release avoids abrupt music-volume steps around each spoken line.
const narrationDuck = (seconds: number) => Math.min(1, ...voiceoverCues.map((cue) => {
  const end = cue.start + voiceoverDurations[cue.id];
  return interpolate(seconds, [cue.start - 0.3, cue.start, end + 0.1, end + 0.5], [1, 0.44, 0.44, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
}));

export const Soundtrack: React.FC = () => {
  const mainMusicFrames = toFrames(TOTAL_DURATION_SECONDS - MUSIC_DROP_SECONDS);
  return (
    <>
      <Sequence durationInFrames={toFrames(MUSIC_DROP_SECONDS)}>
        <Audio
          src={staticFile("audio/music_hook.mp3")}
          volume={(frame) => interpolate(frame / FPS, [0, 1, 13.8, 16.9], [0, 0.42, 0.42, 0.08], { extrapolateRight: "clamp" }) * narrationDuck(frame / FPS)}
        />
      </Sequence>
      <Sequence from={toFrames(MUSIC_DROP_SECONDS)} durationInFrames={mainMusicFrames}>
        <Audio
          src={staticFile("audio/music_main_light.mp3")}
          volume={(frame) => {
            const seconds = MUSIC_DROP_SECONDS + frame / FPS;
            const ducked = 0.4 * narrationDuck(seconds);
            const fadeOut = interpolate(seconds, [TOTAL_DURATION_SECONDS - 3, TOTAL_DURATION_SECONDS], [1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return ducked * fadeOut;
          }}
        />
      </Sequence>
      {voiceoverCues.map((cue) => (
        <Sequence key={cue.id} from={toFrames(cue.start)} durationInFrames={toFrames(voiceoverDurations[cue.id] + 0.3)}>
          <Audio src={staticFile(`audio/vo/${cue.id}.mp3`)} volume={1} />
        </Sequence>
      ))}
      {soundEffectCues.map((cue, index) => (
        <Sequence key={`${cue.id}-${index}`} from={toFrames(cue.at)} durationInFrames={toFrames(cue.duration ?? 3)}>
          <Audio src={staticFile(`audio/sfx/${cue.id}.mp3`)} volume={(frame) => cue.volume * interpolate(
            frame / FPS, [0, 0.04, (cue.duration ?? 3) - 0.12, cue.duration ?? 3], [0, 1, 1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          )} />
        </Sequence>
      ))}
    </>
  );
};
