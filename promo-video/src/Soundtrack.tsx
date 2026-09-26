import React from "react";
import { Audio, interpolate, Sequence, staticFile } from "remotion";
import { FPS, MUSIC_DROP_SECONDS, scenes, toFrames, TOTAL_DURATION_SECONDS, voiceoverCues, voiceoverDurations } from "./timeline";

type SoundEffectCue = { id: string; at: number; volume: number };

const sceneBoundaries = [
  scenes.askAnything.start,
  scenes.jumpToMoment.start,
  scenes.comments.start,
  scenes.followUps.start,
  scenes.itWatches.start,
  scenes.itReads.start,
  scenes.library.start,
];

export const soundEffectCues: SoundEffectCue[] = [
  { id: "page_flip", at: 1.1, volume: 0.55 },
  { id: "keyboard_typing", at: 5.4, volume: 0.35 },
  { id: "scrub_whoosh", at: 10.2, volume: 0.3 },
  { id: "scrub_whoosh", at: 11.9, volume: 0.3 },
  { id: "riser", at: 14.55, volume: 0.6 },
  { id: "impact", at: MUSIC_DROP_SECONDS, volume: 0.9 },
  // Five site clicks, one every two beats.
  ...[0, 1, 2, 3, 4].map((index) => ({ id: "ui_click", at: 20 + index, volume: 0.6 })),
  ...[0, 1, 2, 3, 4].map((index) => ({ id: "whoosh", at: 19.55 + index, volume: 0.22 })),
  // Timestamp-jump transitions between product beats.
  ...sceneBoundaries.map((at) => ({ id: "scrub_whoosh", at: at - 0.1, volume: 0.42 })),
  // Real clicks and answers landing inside the recordings.
  { id: "ui_pop", at: scenes.askAnything.start + 3.45, volume: 0.45 },
  { id: "ui_click", at: scenes.jumpToMoment.start + 4.19, volume: 0.6 },
  { id: "ui_pop", at: scenes.comments.start + 3.0, volume: 0.45 },
  { id: "ui_pop", at: scenes.followUps.start + 2.7, volume: 0.45 },
  { id: "ui_click", at: scenes.followUps.start + 8.2, volume: 0.6 },
  { id: "ui_pop", at: scenes.itWatches.start + 3.7, volume: 0.45 },
  { id: "whoosh", at: scenes.itWatches.start + 5.9, volume: 0.45 },
  { id: "ui_click", at: scenes.itReads.start + 5.2, volume: 0.6 },
  { id: "shimmer", at: scenes.itReads.start + 8.2, volume: 0.6 },
  { id: "book_close", at: scenes.callback.start + 1.5, volume: 0.7 },
  { id: "impact", at: scenes.endCard.start + 0.2, volume: 0.35 },
];

const isNarrationPlaying = (seconds: number) =>
  voiceoverCues.some((cue) => seconds >= cue.start - 0.15 && seconds <= cue.start + voiceoverDurations[cue.id] + 0.2);

export const Soundtrack: React.FC = () => {
  const mainMusicFrames = toFrames(TOTAL_DURATION_SECONDS - MUSIC_DROP_SECONDS);
  return (
    <>
      <Sequence durationInFrames={toFrames(MUSIC_DROP_SECONDS)}>
        <Audio
          src={staticFile("audio/music_hook.mp3")}
          volume={(frame) => interpolate(frame / FPS, [0, 1, 13.8, 16.9], [0, 0.42, 0.42, 0.08], { extrapolateRight: "clamp" })}
        />
      </Sequence>
      <Sequence from={toFrames(MUSIC_DROP_SECONDS)} durationInFrames={mainMusicFrames}>
        <Audio
          src={staticFile("audio/music_main.mp3")}
          volume={(frame) => {
            const seconds = MUSIC_DROP_SECONDS + frame / FPS;
            const ducked = isNarrationPlaying(seconds) ? 0.2 : 0.46;
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
        <Sequence key={`${cue.id}-${index}`} from={toFrames(cue.at)} durationInFrames={toFrames(3)}>
          <Audio src={staticFile(`audio/sfx/${cue.id}.mp3`)} volume={cue.volume} />
        </Sequence>
      ))}
    </>
  );
};
