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

// Narration ducking: the music dips under every spoken line so the voice sits about 15-20 LU above
// the bed (BS.1770 loudness measured per line). Everything is derived from voiceoverCues and
// voiceoverDurations, so the ducking follows the narration when cues move.
const DUCK_ATTACK_SECONDS = 0.25; // The music is fully down when a line starts.
const DUCK_RELEASE_SECONDS = 0.6; // The music comes back over this time after a line ends.
const DUCK_MIN_SWELL_SECONDS = 0.4; // Shortest stretch at full level worth letting the music back up for.
// Lines closer together than this stay under one duck instead of the music bobbing up between them.
const DUCK_BRIDGE_GAP_SECONDS = DUCK_ATTACK_SECONDS + DUCK_RELEASE_SECONDS + DUCK_MIN_SWELL_SECONDS;
// Depth under narration for each music cue. music_main is mixed hotter than music_hook, so it dips further.
const HOOK_MUSIC_DUCK_DB = -14;
const MAIN_MUSIC_DUCK_DB = -20;

type NarrationSpan = { start: number; end: number };

// Spoken stretches heard over one music cue. Spans never bridge across cues, so the music
// drop at MUSIC_DROP_SECONDS still lands at full level before the next line pulls it down.
const narrationSpansDuring = (musicStart: number, musicEnd: number) => {
  const spans: NarrationSpan[] = [];
  const lines = voiceoverCues
    .map((cue) => ({ start: cue.start, end: cue.start + voiceoverDurations[cue.id] }))
    .filter((line) => line.end > musicStart && line.start < musicEnd)
    .sort((a, b) => a.start - b.start);
  for (const line of lines) {
    const previous = spans[spans.length - 1];
    if (previous && line.start - previous.end < DUCK_BRIDGE_GAP_SECONDS) {
      previous.end = Math.max(previous.end, line.end);
    } else {
      spans.push(line);
    }
  }
  return spans;
};

const smoothstep = (progress: number) => progress * progress * (3 - 2 * progress);

// Returns the gain multiplier for a music cue at a given second. The ramp is eased and runs in
// decibels, so the dip sounds even all the way down and has no corners.
const createNarrationDuck = (musicStart: number, musicEnd: number, duckDb: number) => {
  const spans = narrationSpansDuring(musicStart, musicEnd);
  return (seconds: number) => {
    const duckAmount = Math.max(0, ...spans.map(({ start, end }) => smoothstep(interpolate(
      seconds,
      [start - DUCK_ATTACK_SECONDS, start, end, end + DUCK_RELEASE_SECONDS],
      [0, 1, 1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    ))));
    return 10 ** ((duckDb * duckAmount) / 20);
  };
};

const hookMusicDuck = createNarrationDuck(0, MUSIC_DROP_SECONDS, HOOK_MUSIC_DUCK_DB);
const mainMusicDuck = createNarrationDuck(MUSIC_DROP_SECONDS, TOTAL_DURATION_SECONDS, MAIN_MUSIC_DUCK_DB);

export const Soundtrack: React.FC = () => {
  const mainMusicFrames = toFrames(TOTAL_DURATION_SECONDS - MUSIC_DROP_SECONDS);
  return (
    <>
      <Sequence durationInFrames={toFrames(MUSIC_DROP_SECONDS)}>
        <Audio
          src={staticFile("audio/music_hook.mp3")}
          volume={(frame) => interpolate(frame / FPS, [0, 1, 13.8, 16.9], [0, 0.42, 0.42, 0.08], { extrapolateRight: "clamp" }) * hookMusicDuck(frame / FPS)}
        />
      </Sequence>
      <Sequence from={toFrames(MUSIC_DROP_SECONDS)} durationInFrames={mainMusicFrames}>
        <Audio
          src={staticFile("audio/music_main.mp3")}
          volume={(frame) => {
            const seconds = MUSIC_DROP_SECONDS + frame / FPS;
            const ducked = 0.4 * mainMusicDuck(seconds);
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
